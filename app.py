import gradio as gr
import requests
import pandas as pd
import math
import time
import os
import logging
from opencensus.ext.azure.log_exporter import AzureLogHandler
from dotenv import load_dotenv

load_dotenv()

# --- Configuration ---
N8N_WEBHOOK_URL = os.getenv('N8N_WEBHOOK_URL')
BEARER_TOKEN = os.getenv('BEARER_TOKEN')
APP_USER = os.getenv('APP_USER')
APP_PASSWORD = os.getenv('APP_PASSWORD')
APP_AUTH = (APP_USER, APP_PASSWORD) if APP_USER and APP_PASSWORD else None
APPINSIGHTS_CONNECTION_STRING = os.getenv('APPLICATIONINSIGHTS_CONNECTION_STRING')

# --- Logger Setup ---
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Add a console handler for local development and standard output
if not any(isinstance(handler, logging.StreamHandler) for handler in logger.handlers):
    console_handler = logging.StreamHandler()
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

# Add Azure Application Insights handler if the connection string is available
if APPINSIGHTS_CONNECTION_STRING:
    azure_handler = AzureLogHandler(connection_string=APPINSIGHTS_CONNECTION_STRING)
    logger.addHandler(azure_handler)
    logger.info("Application Insights logger configured.")

# --- SVG Icons ---
KPI_ICONS = {
    "prompt": """<svg xmlns="http://www.w3.org/2000/svg" class="icon" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M10 20l4-16m4 4l-4 4-4-4-4 4" /></svg>""",
    "tokens": """<svg xmlns="http://www.w3.org/2000/svg" class="icon" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M9 7h6m0 10v-3m-3 3h.01M9 17h.01M9 14h.01M12 14h.01M15 11h.01M12 11h.01M9 11h.01M12 8h.01M15 8h.01M15 14h.01M18 8h.01M6 8h.01M6 11h.01M6 14h.01M6 17h.01" /></svg>""",
    "cost": """<svg xmlns="http://www.w3.org/2000/svg" class="icon" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M12 8c-1.657 0-3 .895-3 2s1.343 2 3 2 3 .895 3 2-1.343 2-3 2m0-8c1.11 0 2.08.402 2.599 1M12 8V7m0 1v.01" /></svg>""",
    "lines": """<svg xmlns="http://www.w3.org/2000/svg" class="icon" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M4 6h16M4 10h16M4 14h16M4 18h16" /></svg>"""
}

# --- Data Processing Function ---
# --- Data Processing Function ---
def process_invoice_data(pdf_file, progress=gr.Progress()):
    initial_updates = {
        status_output: gr.update(value=""),
        results_col: gr.update(visible=False),
        placeholder_col: gr.update(visible=True),
        validated_status_box: gr.update(visible=False),
        mismatch_status_box: gr.update(visible=False)
    }
    if pdf_file is None:
        logger.warning("Invoice processing attempt failed: No PDF file was uploaded.")
        initial_updates[status_output] = gr.update(value="<div class='status-box error'>❌ Please upload a PDF file.</div>")
        return initial_updates

    filename = os.path.basename(pdf_file.name)
    logger.info("Starting invoice processing for: %s", filename)
    headers = {'Authorization': f'Bearer {BEARER_TOKEN}'}
    
    try:
        progress(0, desc="🚀 Analyzing Document...")
        with open(pdf_file.name, 'rb') as f:
            files = {'file': (pdf_file.name, f, 'application/pdf')}
            response = requests.post(N8N_WEBHOOK_URL, headers=headers, files=files, timeout=600)
            response.raise_for_status()
        logger.info("Successfully received data from webhook for: %s", filename)
        progress(0.9, desc="✅ Success! Formatting results...")
        json_data = response.json()

    except requests.exceptions.RequestException as e:
        logger.error("Request to webhook failed for file: %s. Error: %s", filename, str(e), exc_info=True)
        initial_updates[status_output] = gr.update(value=f"<div class='status-box error'>❌ A network error occurred.</div>")
        return initial_updates

    try:
        json_data = response.json()
        content = json_data.get('message', {}).get('content', {})
        
        prompt_version = content.get('Prompt_Version', 'N/A')
        tokens_used = content.get('NoOfTokensUsed', 'N/A')
        
        # FIX: Handle potential commas in cost value.
        cost_raw = content.get('GPTCostIncurred', '0')
        cost = f"${float(str(cost_raw).replace(',', '')):.4f}"

        line_items_raw = content.get('service_locations', [{}])[0].get('line_items', [])
        line_count = len(line_items_raw)
        
        # FIX: Handle potential commas in line item totals and the main invoice total.
        line_total_sum = sum(float(str(item.get('total', '0')).replace(',', '')) for item in line_items_raw)
        invoice_total_raw = content.get('invoice_total', '0')
        invoice_total = float(str(invoice_total_raw).replace(',', ''))
        
        # Determine which status box to show
        validation_status_update = gr.update(visible=False)
        mismatch_status_update = gr.update(visible=False)
        if math.isclose(invoice_total, line_total_sum, rel_tol=1e-2):
            logger.info("Validation successful for %s. Invoice Total: $%s, Line Sum: $%s", filename, invoice_total, line_total_sum)
            validation_status_update = gr.update(visible=True)
        else:
            logger.warning("Validation mismatch for %s. Invoice Total: $%s, Line Sum: $%s", filename, invoice_total, line_total_sum)
            mismatch_status_update = gr.update(visible=True, value=f"MISMATCH (Lines Sum: ${line_total_sum:,.2f})")

        
        # --- Build Enhanced Header HTML ---
        # ... (HTML building logic remains the same)
        service_locations_html = ""
        service_locations_data = content.get('service_locations', [])
        for loc in service_locations_data:
            addr = loc.get('address', {})
            full_address = f"{addr.get('street', '') or ''} {addr.get('city', '') or ''}, {addr.get('state', '') or ''} {addr.get('zip', '') or ''}".strip(", ")
            service_locations_html += f"<dt>{loc.get('location_name', 'N/A')}</dt><dd>{full_address or 'Address not found'}</dd>"

        header_html = f"""
            <div class='results-header-grid'>
                <dl class='header-details-list'>
                    <div><dt>Invoice #</dt><dd>{content.get('invoice_number', 'N/A')}</dd></div>
                    <div><dt>Invoice Total</dt><dd>${invoice_total:,.2f}</dd></div>
                    <div><dt>Accrual Date</dt><dd>{content.get('accrual_date', 'N/A')}</dd></div>
                    <div><dt>Due Date</dt><dd>{content.get('due_date', 'N/A')}</dd></div>
                    <div class='service-location-item'>{service_locations_html}</div>
                </dl>
            </div>
        """
        
        # --- Build Line Items DataFrame with Total Row ---
        line_items_df = pd.DataFrame([
            {
                "Line #": i, 
                "Date": item.get('date'), 
                "Description": item.get('description'), 
                "Qty": item.get('quantity'), 
                # FIX: Handle potential commas here as well to ensure data is numeric.
                "Total": float(str(item.get('total', '0')).replace(',', ''))
            }
            for i, item in enumerate(line_items_raw, 1)
        ])

        if not line_items_df.empty:
            total_row = pd.DataFrame([{'Description': 'Subtotal', 'Total': line_total_sum}], index=[''])
            line_items_df = pd.concat([line_items_df, total_row])
            # Format the 'Total' column as currency string for display
            line_items_df['Total'] = line_items_df['Total'].apply(lambda x: f"${x:,.2f}" if pd.notna(x) else "")
        
        
        final_updates = {
            status_output: gr.update(value="<div class='status-box success'>✅ Analysis Complete.</div>"),
            results_col: gr.update(visible=True),
            placeholder_col: gr.update(visible=False),
            results_header: gr.update(value=header_html),
            kpi_prompt: gr.update(value=f"<div class='kpi-icon'>{KPI_ICONS['prompt']}</div><div><h3>Prompt Version</h3><p>{prompt_version}</p></div>"),
            kpi_tokens: gr.update(value=f"<div class='kpi-icon'>{KPI_ICONS['tokens']}</div><div><h3>Tokens Used</h3><p>{tokens_used}</p></div>"),
            kpi_cost: gr.update(value=f"<div class='kpi-icon'>{KPI_ICONS['cost']}</div><div><h3>Cost Incurred</h3><p>{cost}</p></div>"),
            kpi_lines: gr.update(value=f"<div class='kpi-icon'>{KPI_ICONS['lines']}</div><div><h3>Line Items</h3><p>{line_count}</p></div>"),
            line_items_table: gr.update(value=line_items_df),
            json_output: gr.update(value=json_data),
            validated_status_box: validation_status_update,
            mismatch_status_box: mismatch_status_update,
        }
        logger.info("Successfully completed analysis for: %s", filename)
        return final_updates
        
    except Exception as e:
        logger.error("Failed to parse webhook response for file: %s. Error: %s", filename, str(e), exc_info=True)
        initial_updates[status_output] = gr.update(value=f"<div class='status-box error'>❌ Error processing response data.</div>")
        return initial_updates
# --- CSS Block Inspired by Salient Tailwind UI ---
css = """
body, #root { font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif; background-color: #f3f4f6; }
h1, h2, h3, p { margin: 0; padding: 0; }
h1 { font-size: 1.5rem; font-weight: 700; color: #111827; letter-spacing: -0.5px; }
h2 { font-size: 1.125rem; font-weight: 600; color: #111827; }
h3 { font-size: 0.875rem; font-weight: 500; color: #6b7280; }
.gradio-container { background: transparent !important; border: none !important; box-shadow: none !important; max-width: 100% !important; padding: 0 !important; }
#main-layout { display: grid; grid-template-columns: 340px 1fr; min-height: 100vh; }
#sidebar { background-color: #ffffff; color: #374151; padding: 1.5rem; display: flex; flex-direction: column; gap: 1.5rem; border-right: 1px solid #e5e7eb; }
#main-content { padding: 2rem; display: flex; flex-direction: column; gap: 1.5rem; }
#sidebar-header p { color: #6b7280; font-size: 0.875rem; margin-top: 0.5rem; }
#parse-button { background-color: #4f46e5; color: white !important; font-weight: 600; border-radius: 0.5rem; border: none; }
.status-box { margin-top: 1rem; padding: 0.75rem; border-radius: 0.5rem; font-weight: 500; text-align: center; }
.status-box.success { background-color: #10b9811a; color: #059669; }
.status-box.error { background-color: #ef44441a; color: #dc2626; }
footer { display: none !important; }
#placeholder-col { text-align: center; margin: auto; }
.placeholder-content { display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 1rem; color: #6b7280; padding: 4rem 2rem; border: 2px dashed #d1d5db; border-radius: 0.75rem; background-color: #fafafa; }
.placeholder-content svg { width: 3rem; height: 3rem; color: #9ca3af; }
.placeholder-content h3 { font-size: 1.125rem; font-weight: 600; color: #374151; }
.placeholder-content p { max-width: 300px; }
.content-card { background-color: white; border-radius: 0.75rem; padding: 1.5rem; border: 1px solid #e5e7eb; }
.results-header-title { display: flex; justify-content: space-between; align-items: flex-start; }
.validation-status-badge { font-size: 0.75rem; font-weight: 600; padding: 0.25rem 0.75rem; border-radius: 9999px; text-transform: uppercase; letter-spacing: 0.05em; margin-left: 1rem; }
.status-validated { background-color: #dcfce7; color: #166534; }
.status-mismatch { background-color: #fee2e2; color: #991b1b; }
.header-details-list { border-top: 1px solid #e5e7eb; margin-top: 1rem; padding-top: 1rem; display: grid; grid-template-columns: repeat(2, 1fr); gap: 1rem; }
.header-details-list dt { font-size: 0.875rem; color: #6b7280; margin-bottom: 0.25rem; }
.header-details-list dd { font-size: 1rem; font-weight: 600; color: #111827; }
.service-location-item { grid-column: span 2 / span 2; }
#kpi-row { display: grid; grid-template-columns: repeat(4, 1fr); gap: 1.5rem; }
.kpi-card { display: flex; align-items: center; gap: 1rem; background: white; border-radius: 0.75rem; padding: 1.5rem; border: 1px solid #e5e7eb; }
.kpi-card .icon { width: 2rem; height: 2rem; color: #4f46e5; }
.kpi-card p { font-size: 1.5rem; font-weight: 700; color: #111827; }
.kpi-prompt { background-color: #eff6ff; border-color: #dbeafe; }
.kpi-prompt .icon { color: #2563eb; }
.kpi-tokens { background-color: #f0fdf4; border-color: #dcfce7; }
.kpi-tokens .icon { color: #16a34a; }
.kpi-cost { background-color: #fefce8; border-color: #fef08a; }
.kpi-cost .icon { color: #ca8a04; }
.kpi-lines { background-color: #faf5ff; border-color: #f3e8ff; }
.kpi-lines .icon { color: #9333ea; }
.gr-dataframe table tr:last-child { font-weight: 700; background-color: #f9fafb; border-top: 2px solid #e5e7eb; }
.progress-bar { background-color: #e5e7eb !important; border-radius: 0.5rem; }
.progress-bar-indicator { background-color: #4f46e5 !important; border-radius: 0.5rem; }
.progress-text { color: #111827 !important; font-weight: 500; }
"""

# --- Gradio UI Layout ---
with gr.Blocks(css=css, theme=gr.themes.Base()) as app:
    with gr.Row(elem_id="main-layout"):
        # --- Sidebar ---
        with gr.Column(scale=1, elem_id="sidebar"):
            gr.Markdown("<div id='sidebar-header'><h1>Invoice Intelligence</h1><p>An AI-powered document analysis tool.</div>", elem_id="logo-area")
            pdf_upload = gr.File(label="Upload Invoice PDF", file_types=[".pdf"])
            parse_button = gr.Button("✨ Analyze Invoice", elem_id="parse-button")
            status_output = gr.HTML()

        # --- Main Content Area ---
        with gr.Column(scale=4, elem_id="main-content"):
            gr.Markdown("<h2>Dashboard</h2>")
            with gr.Column(elem_id="placeholder-col") as placeholder_col:
                gr.HTML("""
                    <div class="placeholder-content">
                        <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor">
                          <path stroke-linecap="round" stroke-linejoin="round" d="M19.5 14.25v-2.625a3.375 3.375 0 0 0-3.375-3.375h-1.5A1.125 1.125 0 0 1 13.5 7.125v-1.5a3.375 3.375 0 0 0-3.375-3.375H8.25m.75 12 3 3m0 0 3-3m-3 3v-6m-1.5-9H5.625c-.621 0-1.125.504-1.125 1.125v17.25c0 .621.504 1.125 1.125 1.125h12.75c.621 0 1.125-.504 1.125-1.125V11.25a9 9 0 0 0-9-9Z" />
                        </svg>
                        <h3>Upload an invoice to get started</h3>
                        <p>The analysis results will appear here once you upload and process a PDF file.</p>
                    </div>
                """)

            with gr.Column(visible=False) as results_col:
                results_header = gr.HTML(elem_classes="content-card")
                
                with gr.Row(elem_id="kpi-row"):
                    kpi_prompt = gr.HTML(elem_classes="kpi-card kpi-prompt")
                    kpi_tokens = gr.HTML(elem_classes="kpi-card kpi-tokens")
                    kpi_cost = gr.HTML(elem_classes="kpi-card kpi-cost")
                    kpi_lines = gr.HTML(elem_classes="kpi-card kpi-lines")
                
                with gr.Group(elem_classes="content-card"):
                    with gr.Row():
                         gr.Markdown("<h2>Line Items</h2>")
                         with gr.Column():
                            validated_status_box = gr.Textbox("VALIDATED", label="Validation", visible=False, interactive=False, elem_classes="validation-status-badge status-validated")
                            mismatch_status_box = gr.Textbox("MISMATCH", label="Validation", visible=False, interactive=False, elem_classes="validation-status-badge status-mismatch")
                    line_items_table = gr.DataFrame(interactive=False, show_label=False, wrap=True)

                with gr.Accordion("Full JSON Response", open=False):
                    json_output = gr.JSON(elem_classes="content-card")

    # --- Event Handling ---
    parse_button.click(
        fn=process_invoice_data,
        inputs=[pdf_upload],
        outputs=[
            status_output, results_col, placeholder_col, results_header, 
            kpi_prompt, kpi_tokens, kpi_cost, kpi_lines,
            line_items_table, json_output,
            validated_status_box, mismatch_status_box
        ]
    )

if __name__ == "__main__":
    app.launch(
        auth=APP_AUTH,
        server_name="0.0.0.0",
        server_port=8000  # match EXPOSE in Dockerfile
    )
# --- End of app.py ---
