"""Standalone, optional Playwright smoke against running API/worker/HTTP frontend.

uv run --with playwright python tests/browser_smoke.py
Uses synthetic accounts/documents, not the five-report ML acceptance test.
"""

import os
import time
import zipfile
from io import BytesIO

from playwright.sync_api import expect, sync_playwright


def main():
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context(accept_downloads=True)
        page = context.new_page()
        errors = []
        page.on("pageerror", lambda error: errors.append(type(error).__name__))
        page.goto(os.getenv("PM_BROWSER_URL", "http://localhost:5173"))
        expect(page.get_by_role("heading", name="Вход", exact=True)).to_be_visible()
        page.evaluate("""localStorage.setItem('ai-presentations:source:v1', JSON.stringify({
            state:{draft:{text:'OLD PRIVATE DEMO TEXT', title:'OLD PRIVATE TITLE', slideCount:8}},
            version:0}))""")
        page.get_by_role("button", name="Создать аккаунт", exact=True).click()
        account = f"browser-{time.time_ns()}"
        page.get_by_label("Логин", exact=True).fill(account)
        page.get_by_label("Пароль — 15–128 символов").fill("browser test password long")
        page.get_by_role("button", name="Зарегистрироваться", exact=True).click()
        expect(page.get_by_role("button", name="Выйти", exact=True)).to_be_visible()
        expect(page.get_by_text("OLD PRIVATE TITLE", exact=True)).to_have_count(0)
        source = page.get_by_label("Текст доклада или план выступления", exact=True)
        expect(source).to_have_value("")
        source.fill("Синтетический доклад для проверки API, без настоящей генерации. " * 5)
        events = []

        def requested(request):
            if request.method == "GET" and "/api/v1/presentations/" in request.url:
                events.append("document")

        def job_status(route):
            response = route.fetch()
            if response.status == 200 and response.json()["status"] == "succeeded":
                events.append("completed")
            # Record completion before the browser can consume the response.
            route.fulfill(response=response)

        page.on("request", requested)
        page.route("**/api/v1/jobs/*", job_status)
        page.get_by_role("button", name="Создать презентацию", exact=True).click()
        expect(page.get_by_role("heading", name="Правка командой", exact=True)).to_be_visible(
            timeout=20000
        )
        # No eager document read may race with the successful polling result.
        assert events and events[0] == "completed", events
        assert "document" in events, events
        page.remove_listener("request", requested)
        page.unroute("**/api/v1/jobs/*", job_status)
        page.get_by_role("button", name="Полная перегенерация", exact=True).click()
        page.get_by_role("button", name="Создать презентацию", exact=True).click()
        expect(page.get_by_role("button", name="Вернуться к форме", exact=True)).to_be_visible()
        page.get_by_role("button", name="Вернуться к форме", exact=True).click()
        expect(page.get_by_role("button", name="Возобновить ожидание", exact=True)).to_be_visible()
        page.reload()
        expect(page.get_by_role("heading", name="Правка командой", exact=True)).to_be_visible(
            timeout=20000
        )
        expect(page.locator("#presentation-title")).to_have_attribute("readonly", "")
        expect(page.get_by_role("button", name="Разделить слайд", exact=True)).to_have_count(0)
        page.get_by_label("Что изменить", exact=True).fill("Тестовая правка заметок")
        page.get_by_label("Номера слайдов через запятую (необязательно)").fill("3")
        page.get_by_role("button", name="Применить команду", exact=True).click()
        expect(page.get_by_role("button", name="Вернуться к форме", exact=True)).to_be_visible()
        expect(page.get_by_label("Что изменить", exact=True)).to_be_enabled(timeout=20000)
        expect(page.get_by_label("Что изменить", exact=True)).to_have_value("")
        page.get_by_role("button", name="Скачать PPTX", exact=True).click()
        with page.expect_download() as downloaded:
            page.get_by_role("dialog").get_by_role(
                "button", name="Скачать PPTX", exact=True
            ).click()
        with zipfile.ZipFile(BytesIO(open(downloaded.value.path(), "rb").read())) as archive:
            assert "ppt/slides/slide6.xml" in archive.namelist()
            assert (
                "Тестовая правка фикстуры"
                in archive.read("ppt/notesSlides/notesSlide3.xml").decode()
            )
        page.get_by_role("dialog").wait_for(state="hidden")
        keys = page.evaluate("Object.keys(localStorage).filter(k => k.startsWith('pm:current:'))")
        assert len(keys) == 1
        reference = page.evaluate("key => localStorage.getItem(key)", keys[0])
        assert "Синтетический доклад" not in reference and "Тестовая правка" not in reference
        page.get_by_role("button", name="Выйти", exact=True).click()
        expect(page.get_by_role("heading", name="Вход", exact=True)).to_be_visible()
        expect(page.get_by_role("heading", name="Правка командой", exact=True)).to_have_count(0)
        page.get_by_role("button", name="Создать аккаунт", exact=True).click()
        page.get_by_label("Логин", exact=True).fill(f"other-{time.time_ns()}")
        page.get_by_label("Пароль — 15–128 символов").fill("browser other password long")
        page.get_by_role("button", name="Зарегистрироваться", exact=True).click()
        expect(page.get_by_role("button", name="Выйти", exact=True)).to_be_visible()
        expect(page.get_by_label("Текст доклада или план выступления", exact=True)).to_have_value(
            ""
        )
        expect(page.locator("#presentation-title")).to_have_count(0)
        assert not errors, errors
        browser.close()
        print(
            "PASS: register -> generate without race -> regenerate -> stop waiting -> "
            "reload -> preview -> revise -> "
            "PPTX -> logout -> other user"
        )


if __name__ == "__main__":
    main()
