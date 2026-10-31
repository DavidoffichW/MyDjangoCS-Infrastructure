from __future__ import annotations

from django.contrib.staticfiles.testing import StaticLiveServerTestCase

from workflows.models import ExecutionAttempt, Job, WorkflowStep


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

    def test_double_execution_and_csrf_failure_are_controlled_server_side(self) -> None:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            page = browser.new_page()
            page.set_default_timeout(10_000)
            self.create_workflow(page, "Concurrent browser workflow")
            page.get_by_label("Operation").select_option("summarize")
            page.get_by_role("button", name="Add operation").click()
            page.locator(".step-row strong", has_text="Calculate summary").wait_for()
            page.get_by_label("Input values").fill("1, 2")
            page.get_by_label("Idempotency key").fill("browser-double-submit")
            page.get_by_role("button", name="Admit job").click()
            page.get_by_role("link", name="Inspect").click()

            statuses = page.evaluate(
                """
                async () => {
                  const token = document.cookie.split('; ')
                    .find((item) => item.startsWith('csrftoken='))
                    .split('=')[1];
                  const options = {
                    method: 'POST',
                    credentials: 'same-origin',
                    headers: {'HX-Request': 'true', 'X-CSRFToken': token},
                  };
                  const url = `${location.pathname}execute/`;
                  const responses = await Promise.all([fetch(url, options), fetch(url, options)]);
                  return Promise.all(responses.map(async (response) => ({
                    status: response.status, body: await response.text()
                  })));
                }
                """
            )
            job_id = page.url.rstrip("/").split("/")[-1]

            rejected = page.evaluate(
                """
                async () => (await fetch(`${location.pathname}retry/`, {
                  method: 'POST', credentials: 'same-origin'
                })).status
                """
            )
            self.assertEqual(rejected, 403)
            browser.close()
        job = Job.objects.get(id=job_id)
        observed_statuses = sorted(item["status"] for item in statuses)
        self.assertEqual(observed_statuses[0], 200, statuses)
        self.assertIn(observed_statuses[1], {409, 503}, statuses)
        self.assertNotIn(500, observed_statuses, statuses)
        self.assertEqual(job.state, Job.State.SUCCEEDED)
        self.assertEqual(ExecutionAttempt.objects.filter(job=job).count(), 1)

    def test_dynamic_edit_reorder_remove_and_stale_form_behavior(self) -> None:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            page = browser.new_page()
            page.set_default_timeout(10_000)
            self.create_workflow(page, "Editing workflow")

            page.get_by_label("Operation").select_option("scale")
            page.get_by_label("Parameter").fill("2")
            page.get_by_role("button", name="Add operation").click()
            page.locator(".step-row strong", has_text="Scale every value").wait_for()
            page.get_by_label("Operation").select_option("summarize")
            page.get_by_label("Parameter").fill("")
            page.get_by_role("button", name="Add operation").click()
            page.locator(".step-row").nth(1).wait_for()
            self.assertEqual(page.locator(".step-row").count(), 2)

            second = page.locator(".step-row").nth(1)
            second.get_by_title("Move up").click()
            page.locator(".step-row").first.locator(
                "strong", has_text="Calculate summary"
            ).wait_for()
            page.locator(".step-row").nth(1).get_by_role("link", name="Edit").click()
            page.get_by_role("button", name="Save operation").wait_for()
            page.get_by_label("Parameter").fill("3")
            edit_action = page.locator("#step-editor form.stack").get_attribute("action")
            with page.expect_response(
                lambda response: response.url.endswith(edit_action)
            ) as edit_response:
                page.get_by_role("button", name="Save operation").click()
            self.assertEqual(edit_response.value.status, 200)
            page.locator(".step-row small", has_text="parameter 3").wait_for()

            page.once("dialog", lambda dialog: dialog.accept())
            with page.expect_response(lambda response: "/delete/" in response.url) as removal:
                page.locator(".step-row").first.get_by_role("button", name="Remove").click()
            self.assertEqual(removal.value.status, 200)
            page.locator(".step-row").nth(1).wait_for(state="detached")
            self.assertEqual(page.locator(".step-row").count(), 1)

            page.locator(".step-row").first.get_by_role("link", name="Edit").click()
            page.get_by_role("button", name="Save operation").wait_for()
            stale_action = page.locator("#step-editor form.stack").get_attribute("action")
            other = browser.new_page()
            other.goto(page.url)
            other.once("dialog", lambda dialog: dialog.accept())
            with other.expect_response(lambda response: "/delete/" in response.url) as deletion:
                other.locator(".step-row").first.get_by_role("button", name="Remove").click()
            self.assertEqual(deletion.value.status, 200)
            with page.expect_response(
                lambda response: response.url.endswith(stale_action)
            ) as response:
                page.get_by_role("button", name="Save operation").click()
            self.assertEqual(response.value.status, 404)
            browser.close()
        self.assertEqual(WorkflowStep.objects.count(), 0)

    def test_ordinary_html_forms_work_without_javascript(self) -> None:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            context = browser.new_context(java_script_enabled=False)
            page = context.new_page()
            page.set_default_timeout(10_000)
            self.create_workflow(page, "No JavaScript workflow")
            page.get_by_label("Operation").select_option("summarize")
            with page.expect_navigation() as navigation:
                page.get_by_role("button", name="Add operation").click()
            self.assertEqual(navigation.value.status, 200)
            self.assertIn("Calculate summary", page.locator("body").inner_text())
            with page.expect_navigation() as removal:
                page.get_by_role("button", name="Remove").click()
            self.assertEqual(removal.value.status, 200)
            self.assertIn("Add the first operation", page.locator("body").inner_text())
            browser.close()
