"""Gradio UI — thin presentation layer over pipeline.py. No business logic lives here; every
callback is a formatting wrapper around one pipeline.* call.
"""

import logging
import os

import gradio as gr

import config
import pipeline
import pipeline_log
import tts
from jingle import generate_jingle
from llm import invoke
from video_h3 import generate_video
from video_fallback import generate_video as generate_video_fallback
from utils import load_prompt, UTF8_ENCODING

pipeline_log.attach()

with open("js/tts.js", encoding=UTF8_ENCODING) as f:
    _tts_js = f.read()

logger = logging.getLogger(__name__)

DEFAULT_TLDS = ["com", "net", "ai", "org", "info", "biz", "io", "co"]
SUGGESTIONS_PLACEHOLDER_SUFFIX = " suggestions generated for you to choose from"

# Forces real dark mode — Gradio's dark-variant CSS only activates under :root.dark.
HEAD_HTML = "<script>document.documentElement.classList.add('dark');</script>"

CUSTOM_CSS = """
#header-banner {
    background: linear-gradient(90deg, #0ea5e9, #6366f1);
    border-radius: 12px;
    padding: 20px 24px;
    margin-bottom: 12px;
}
#header-banner h1 { margin: 0; color: white; }
#header-banner .tagline {
    margin: 6px 0 0;
    font-size: 1.15em;
    font-weight: 500;
    color: rgba(255, 255, 255, 0.9);
}
#header-banner .tagline a {
    color: white;
    text-decoration: underline;
    padding: 0;
    margin: 0;
    display: inline;
}
#header-banner .explanation {
    margin: 10px 0 0;
    font-size: 1.05em;
    line-height: 1.6;
    color: rgba(255, 255, 255, 0.85);
}
#header-banner .explanation a {
    color: white;
    text-decoration: underline;
    padding: 0;
    margin: 0;
    display: inline;
}

.section-card {
    border-radius: 12px !important;
    padding: 16px !important;
}

.status-pill {
    display: inline-block;
    padding: 2px 10px;
    border-radius: 999px;
    font-size: 0.85em;
    font-weight: 600;
}
.status-success { background: #064e3b; color: #6ee7b7; }
.status-error { background: #450a0a; color: #fca5a5; }

.mono textarea, .mono input {
    font-family: "IBM Plex Mono", ui-monospace, Menlo, monospace !important;
}

/* Highlights the whole row a selected cell belongs to, grounded in two classes confirmed to
exist in gradio==6.26.0's own compiled CSS (.cell-selected, .virtual-row) — not a blind guess,
but still tied to this exact pinned version; may stop matching on a future Gradio upgrade. */
.virtual-row:has(.cell-selected) {
    background-color: rgba(14, 165, 233, 0.15) !important;
}

.jingle-audio button.playback {
    display: none !important;
}

.jingle-column {
    justify-content: center !important;
    display: flex !important;
    flex-direction: column !important;
    gap: 8px !important;
}

.jingle-download {
    background: transparent !important;
    border: none !important;
    box-shadow: none !important;
    padding: 0 !important;
}
"""


def _pending(message):
    """Returns a sync callback for the first stage of a two-stage `.click().then()` chain, so a
    slow operation shows immediate feedback instead of an unexplained pause."""
    return lambda: message


def _status_line(result: dict) -> str:
    if result["status"] == "success":
        return "<span class='status-pill status-success'>success</span>"
    return f"<span class='status-pill status-error'>error</span> — {result['detail']}"


def _status_is_successful(status: str) -> bool:
    return "✅" in status


def _format_domain_for_tts(domain: str) -> str:
    return domain.replace(".ai", " dot a-i").replace(".", " dot ")


async def on_tts(text: str):
    """Try MiniMax TTS first; on any failure return (None, text) so the browser TTS JS fires."""
    if not text:
        return None, None
    path = await tts.speak(text)
    if path:
        # MiniMax succeeded — play the mp3, clear tts_output so browser TTS gets empty string
        return gr.Audio(value=path, visible="hidden", autoplay=True), None
    # MiniMax failed — leave tts_output populated so the chained browser TTS JS fires it
    return None, text


async def on_ai_suggest(keyword: str) -> gr.Dropdown:
    if not keyword or not keyword.strip():
        gr.Info("Please describe your app in the textbox on the left.", duration=3)
        return gr.skip()
    prompt = load_prompt("suggest_slds.prompt.txt")
    raw = await invoke(prompt, keyword, max_tokens=config.LLM_MAX_TOKENS_SLDS, temperature=config.LLM_TEMPERATURE_SLDS)
    suggestions = sorted(s.strip().casefold() for s in raw.split(",") if s.strip())
    placeholder = f"{len(suggestions)}{SUGGESTIONS_PLACEHOLDER_SUFFIX}"
    return gr.Dropdown(choices=[placeholder] + suggestions, value=placeholder)


async def on_jingle(domain_name: str, keyword: str):
    if not domain_name or not domain_name.strip():
        gr.Info("Please enter a domain name in the textbox on the left.", duration=3)
        return gr.skip(), gr.skip(), "", gr.Button(interactive=True), gr.skip()
    if not keyword or not keyword.strip():
        gr.Info("Please describe your app in the 'App name / keyword' textbox at the top.", duration=3)
        return gr.skip(), gr.skip(), "", gr.Button(interactive=True), gr.skip()
    try:
        path, lyrics = await generate_jingle(domain_name.strip(), keyword.strip())
        return gr.DownloadButton(value=path, visible=True), gr.Audio(value=path, visible=True), "", gr.Button(interactive=True), lyrics
    except Exception as e:
        logger.exception("Jingle generation failed")
        return gr.skip(), gr.skip(), f"❌ {e}", gr.Button(interactive=True), gr.skip()


async def on_video(domain_name: str, lyrics: str):
    if not lyrics or not lyrics.strip():
        gr.Info("Please generate a jingle first using the 'Play Jingle' button.", duration=3)
        return gr.skip(), gr.skip(), "", gr.Button(interactive=True), gr.skip()
    try:
        try:
            logger.info("Generating video for %s", domain_name.strip())
            path, subtitle_path = await generate_video(domain_name.strip(), lyrics)
        except Exception as e:
            logger.debug("GMI video generation failed (%s) — falling back", e)
            path, subtitle_path = await generate_video_fallback(domain_name.strip(), lyrics)
        logger.info("Video ready: %s", os.path.basename(path))
        return gr.Video(value=path, visible=True), gr.DownloadButton(value=path, visible=True), "", gr.Button(interactive=True), subtitle_path
    except Exception as e:
        logger.exception("Video generation failed")
        return gr.skip(), gr.skip(), f"❌ {e}", gr.Button(interactive=True), gr.skip()


def on_video_play(subtitle_path: str | None):
    # Gradio 6.26.0's VideoPreview can erase the video when its value and
    # subtitles change together. Attach captions only after playback starts,
    # updating subtitles alone so the existing video is preserved.
    return gr.Video(subtitles=subtitle_path) if subtitle_path else gr.skip()


def _format_price(value):
    return f"${value:.2f}" if isinstance(value, (int, float)) else "—"


async def on_search(keyword, tlds, search_all_tlds):
    if not keyword or not keyword.strip():
        return None, "Enter a keyword first."
    tld_filter = None if search_all_tlds else (tlds or None)
    result = await pipeline.run_search(keyword.strip(), tld_filter=tld_filter)
    if result["status"] != "success":
        return None, _status_line(result)
    rows = [
        [
            item.get("domainName"),
            "yes" if item.get("purchasable") else "no",
            _format_price(item.get("purchasePrice")),
            _format_price(item.get("renewalPrice")),
            "yes" if item.get("premium") else "no",
        ]
        for item in result["data"].get("results", [])
    ]
    result_label = 'result' if len(rows) == 1 else 'results'
    return rows, f"Found {len(rows)} {result_label}. Click a row to select it for registration."


def on_select_search_result(evt: gr.SelectData):
    return evt.row_value[0]


async def on_register(domain_name):
    if not domain_name or not domain_name.strip():
        return "Select or type a domain name first."
    result = await pipeline.run_register(domain_name.strip())
    if result["status"] != "success":
        return _status_line(result)
    data = result["data"]
    domain_name = data["domain"]["domainName"]
    return (
        f"✅ Registered **{domain_name}** — order #{data['order']}, "
        f"total paid {_format_price(data['totalPaid'])} for {data['years']} year registration."
    )


with gr.Blocks(title="Sing My Domain") as demo:
    gr.HTML(
        "<div id='header-banner'>"
        "<h1>Sing My Domain</h1>"
        "<p class='tagline'>"
        "AI-powered domain search &amp; registration with jingle and brand video generation."
        "</p>"
        "<p class='explanation'>&bull; Describe your app, search for a domain name, then let "
        "<a href='https://www.minimaxi.com' target='_blank' rel='noopener'>MiniMax</a> "
        "compose a custom jingle and generate a brand video so you can experience the domain "
        "before you register it &mdash; hear it, see it, then decide before paying money."
        "</p>"
        "</div>"
    )

    with gr.Group(elem_classes=["section-card"]):
        with gr.Row():
            keyword = gr.Textbox(label="App name / keyword", placeholder="my-cool-app", scale=2)
            with gr.Column(scale=1):
                ai_suggest_button = gr.Button(
                    "AI Suggest (click for suggestions from AI)", variant="primary", size="sm")
                ai_suggestions = gr.Dropdown(
                    show_label=False, filterable=False, interactive=True)
        tlds = gr.CheckboxGroup(
            DEFAULT_TLDS, value=DEFAULT_TLDS, label="Popular TLDs to search"
        )
        search_all_tlds = gr.Checkbox(
            label="Search all TLDs (ignore the list above)", value=False
        )
        search_button = gr.Button("Search availability", variant="primary")
        search_status = gr.Markdown()
        results_table = gr.Dataframe(
            headers=["domain", "purchasable", "price", "renewal", "premium"],
            datatype=["str", "str", "str", "str", "str"],
            interactive=False,
        )

    with gr.Group(elem_classes=["section-card"]):
        with gr.Row():
            selected_domain = gr.Textbox(label="Domain to register", elem_classes=["mono"], scale=2, max_lines=1)
            if config.GMI_CLOUD_ENABLED:
                with gr.Column(scale=1, elem_classes=["jingle-column"]):
                    with gr.Row():
                        jingle_button = gr.Button("Play Jingle 🎵", variant="primary", size="sm")
                        video_button = gr.Button("Play Video 🎬", variant="primary", size="sm")
                    jingle_status = gr.Markdown()
                    with gr.Row():
                        jingle_download = gr.DownloadButton("Download Jingle", visible=False, size="sm", elem_classes=["jingle-download"])
                        video_download = gr.DownloadButton("Download Video", visible=False, size="sm", elem_classes=["jingle-download"])
        register_button = gr.Button("Register (sandbox mock purchase)", variant="primary")
        register_status = gr.Markdown()
        if config.GMI_CLOUD_ENABLED:
            jingle_audio = gr.Audio(visible=False, show_label=False, autoplay=True, buttons=[], elem_classes=["jingle-audio"])
            jingle_video = gr.Video(visible=False, show_label=False, autoplay=True, loop=True, buttons=[])
            video_subtitles = gr.State(None)
        app_description = gr.State("")
        jingle_lyrics = gr.State("")
        tts_output = gr.Textbox(visible=False)
        tts_audio = gr.Audio(visible="hidden", autoplay=True, show_label=False)

    search_button.click(
        _pending("⏳ Searching…"), outputs=search_status
    ).then(
        on_search,
        inputs=[keyword, tlds, search_all_tlds],
        outputs=[results_table, search_status],
    )
    keyword.submit(
        _pending("⏳ Searching…"), outputs=search_status
    ).then(
        on_search,
        inputs=[keyword, tlds, search_all_tlds],
        outputs=[results_table, search_status],
    )
    search_all_tlds.change(
        lambda checked: gr.CheckboxGroup(interactive=not checked),
        inputs=search_all_tlds,
        outputs=tlds,
    )
    results_table.select(on_select_search_result, outputs=selected_domain)
    ai_suggest_button.click(on_ai_suggest, inputs=keyword, outputs=ai_suggestions).then(
        lambda v: v, inputs=keyword, outputs=app_description
    )
    ai_suggestions.change(lambda v: v if v and not v.endswith(SUGGESTIONS_PLACEHOLDER_SUFFIX) else gr.skip(), inputs=ai_suggestions, outputs=keyword)
    keyword.change(lambda v: v, inputs=keyword, outputs=app_description)
    if config.GMI_CLOUD_ENABLED:
        jingle_button.click(
            lambda: (gr.Button(interactive=False), "⏳ Generating jingle…"),
            outputs=[jingle_button, jingle_status],
        ).then(
            on_jingle,
            inputs=[selected_domain, app_description],
            outputs=[jingle_download, jingle_audio, jingle_status, jingle_button, jingle_lyrics],
        )
        video_button.click(
            lambda: (gr.Button(interactive=False), "⏳ Generating video…"),
            outputs=[video_button, jingle_status],
        ).then(
            on_video,
            inputs=[selected_domain, jingle_lyrics],
            outputs=[jingle_video, video_download, jingle_status, video_button, video_subtitles],
        )
        jingle_video.play(
            on_video_play, inputs=video_subtitles, outputs=jingle_video, queue=False,
        )
    register_button.click(
        _pending("⏳ Registering…"), outputs=register_status
    ).then(
        on_register,
        inputs=selected_domain,
        outputs=register_status,
    ).then(
        lambda status, domain: f"Domain '{_format_domain_for_tts(domain)}' registered successfully at {_format_domain_for_tts('name.com')}." if _status_is_successful(status) else None,
        inputs=[register_status, selected_domain],
        outputs=tts_output,
    ).then(on_tts, inputs=tts_output, outputs=[tts_audio, tts_output]
    ).then(None, inputs=tts_output, js=_tts_js)

    with gr.Accordion("🔷 Pipeline Log — real-time API and AI requests", open=False):
        pipeline_log_output = gr.Textbox(
            value=pipeline_log.get_log,
            lines=10,
            interactive=False,
            show_label=True,
            label=" ",
            elem_classes=["mono"],
            buttons=["copy"],
        )
        with gr.Row():
            gr.Markdown("")
            clear_log_button = gr.Button("Clear", size="sm", scale=0)
    # 1s matches the fastest observed operation (~0.8s) — sub-second polling would fire
    # multiple times per operation with no new entries, adding unnecessary server round-trips.
    gr.Timer(1).tick(pipeline_log.get_log, outputs=pipeline_log_output)
    clear_log_button.click(lambda: (pipeline_log.clear_log() or ""), outputs=pipeline_log_output)


if __name__ == "__main__":
    demo.launch(
        theme=gr.themes.Default(),
        css=CUSTOM_CSS,
        head=HEAD_HTML,
        footer_links=[],
        server_name="0.0.0.0",
        server_port=int(os.environ.get("PORT", 7860)),
    )
