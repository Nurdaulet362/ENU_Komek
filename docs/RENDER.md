# Render Free deployment

This repository can run as a public **demo** using one Render Free Docker Web Service. No paid disk or database is required. Select this GitHub repository and its main branch, Docker runtime, Free instance, and health check `/healthz`. The Dockerfile starts `python server.py --host 0.0.0.0` and reads Render's `PORT`; the public hostname is restricted to `RENDER_EXTERNAL_HOSTNAME`.

## Visitor isolation

`ENU_HOSTED=1` enables temporary private workspaces identified by random Secure, HttpOnly, SameSite=Strict session cookies. Keys, model choices, document permissions, original files, previews and search indexes are scoped to that visitor. Owner `.env` and environment API keys are never inherited by public visitors. Hosted keys stay in server memory, not a shared .env or browser localStorage. Each visitor must enter their own provider API key. Hosted Ollama is disabled.

The public demo starts with an empty document library. No university source documents or developer API keys are bundled or uploaded. Uploads are limited to 3 PDF/DOCX files of at most 5 MB each, with a combined extracted text cap of 300,000 characters. There are at most 12 live visitor workspaces, each with a 30-minute inactivity timeout; the process has a bounded request-thread pool. POST requests require the configured same-site Origin and have a per-session request limit.

## Free-tier limitations

Render Free can spin down after inactivity and discards filesystem changes on restart/redeploy. Visitor settings, keys and uploaded documents are temporary and can be lost earlier than their inactivity timeout when the process restarts. Browser question history can remain, but old source links will require re-uploading the relevant document. This is a competition preview, not a production multi-user service with durable accounts, backups or uptime guarantees.

No owner key should be configured for shared public use. Cloud provider API charges/quotas are separate from Render hosting. Selecting Render Free does not make every model API free.

References: https://render.com/docs/free and https://render.com/docs/web-services
