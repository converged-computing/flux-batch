# Template for the Scribe Journal Consumer
SERVICE_TEMPLATE = """[Unit]
Description=Flux Scribe Journal Consumer
After=network.target

[Service]
ExecStart={python_path} -m flux_batch.service.scribe
Restart=on-failure

[Install]
WantedBy=default.target
"""
