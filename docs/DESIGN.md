# Interface contract

Purpose: help an ENU student find a documented answer and inspect its source.
Primary action: ask a question in Kazakh or Russian. Secondary: browse/upload sources.
Reference: user-provided ENU competition criteria and local PDF/DOCX corpus.

Calm university workspace: forest green, warm off-white, restrained lime and clay accents.
Persistent desktop navigation, question field in the main column, source coverage on the right.
Mobile navigation replaces the sidebar below 700px. Intended viewports: desktop 1440x900,
mobile 390x844. Document titles wrap. No external fonts, trackers or image services.

Content states:
- Loading: visible status, disabled submit; completion replaces the result.
- Empty: library shows explanation; upload remains available.
- Error: connection/request error and retry. Upload errors preserve the dialog.
- Partial: unreadable documents are listed as needing OCR, excluded from retrieval.
- Success: exact source snippets, page/section references, save/copy controls.
- Permission: local single-user app. No account system; remote access rejected by host/origin checks.

Keyboard: labeled fields/buttons, visible focus, Escape dismisses dialogs, focus restored on close,
dialog focus loop, Enter submits, Shift+Enter inserts a new line. Reduced motion supported.

The source role classifier is a usability filter, NOT an authorization boundary.

## Model workspace redesign — 2026-11-03

Primary action remains asking a question; active model is visible in the header and composer.
Navy navigation, white paper canvas, cobalt actions and amber source accents distinguish the
conversation, model configuration and document evidence. Existing framework-free controls stay.

Model settings: provider selector, password field (never prefilled), server-side saved-key status,
refresh/test connection, searchable model list, selected state and save action. Empty model lists
explain the next step. Connection loading disables duplicate actions; errors keep the form intact.
Partial: a successful models.list is not proof that every model permits generateContent; generation
errors prompt switching models. Permission: document snippets go to Google only after an explicit
checkbox is enabled. Questions in Gemini general chat go to Google. Secrets never enter localStorage.

Review targets: 1440x900 desktop, actual 500x812 narrow browser viewport (host minimum width).
375px remains a limitation unless true emulation is available. Review focus labels, keyboard modal
focus trapping, reduced motion, long model ids, input states and horizontal overflow.
