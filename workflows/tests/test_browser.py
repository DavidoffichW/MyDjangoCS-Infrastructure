from __future__ import annotations

from django.contrib.staticfiles.testing import StaticLiveServerTestCase


class BrowserWorkflowTests(StaticLiveServerTestCase):
    def create_workflow(self, page, name: str) -> None:
        page.goto(self.live_server_url)
        page.get_by_label("Name").fill(name)
        with page.expect_navigation() as navigation:
            page.get_by_role("button", name="Create workflow").click()
        self.assertEqual(navigation.value.status, 200, page.locator("body").inner_text())
        self.assertRegex(page.url, r"/workflows/[0-9a-f-]+/$", page.locator("body").inner_text())

    def test_dynamic_workflow_executes_and_displays_result(self) -> None:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            page = browser.new_page()
            page.set_default_timeout(10_000)
            self.create_workflow(page, "Browser workflow")

            page.get_by_label("Operation").select_option("scale")
            page.get_by_label("Parameter").fill("2")
            self.assertEqual(
                page.get_by_role("button", name="Add operation").count(),
                1,
                page.locator("body").inner_text(),
            )
            page.get_by_role("button", name="Add operation").click()
            page.locator(".step-row strong", has_text="Scale every value").wait_for()

            page.get_by_label("Operation").select_option("summarize")
            page.get_by_label("Parameter").fill("")
            page.get_by_role("button", name="Add operation").click()
            page.locator(".step-row strong", has_text="Calculate summary").wait_for()

            page.get_by_label("Input values").fill("1, 2, 3")
            page.get_by_label("Idempotency key").fill("browser-success")
            page.get_by_role("button", name="Admit job").click()
            page.get_by_role("link", name="Inspect").click()
            with page.expect_response(
                lambda response: response.url.endswith("/execute/")
            ) as execution:
                page.get_by_role("button", name="Run now").click()
            self.assertEqual(execution.value.status, 200, page.locator("body").inner_text())
            page.get_by_text("Succeeded", exact=True).wait_for()
            page.get_by_role("link", name="Open immutable result").click()

            page.get_by_text("2", exact=True).wait_for()
            self.assertIn("6", page.locator(".value-list").inner_text())
            self.assertEqual(page.locator(".facts dd").nth(2).inner_text(), "4")
            browser.close()

    def test_injected_failure_is_visible_and_recoverable(self) -> None:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            page = browser.new_page()
            page.set_default_timeout(10_000)
            self.create_workflow(page, "Failure workflow")
            page.get_by_label("Operation").select_option("fail_once")
            page.get_by_role("button", name="Add operation").click()
            page.locator(".step-row strong", has_text="Inject one controlled failure").wait_for()

            page.get_by_label("Input values").fill("5")
            page.get_by_label("Idempotency key").fill("browser-failure")
            page.get_by_role("button", name="Admit job").click()
            page.get_by_role("link", name="Inspect").click()
            with page.expect_response(
                lambda response: response.url.endswith("/execute/")
            ) as execution:
                page.get_by_role("button", name="Run now").click()
            self.assertEqual(execution.value.status, 200, page.locator("body").inner_text())
            page.get_by_text("INJECTED_FAILURE").wait_for()
            page.get_by_role("button", name="Return to queue").click()
            page.get_by_role("button", name="Run now").click()
            page.get_by_text("Succeeded", exact=True).wait_for()
            browser.close()
