from paperang_p1.window import WindowControls, install_native_assets


class FakeWindow:
    def __init__(self, url):
        self.url = url
        self.actions = []

    def get_current_url(self): return self.url
    def minimize(self): self.actions.append('minimize')
    def maximize(self): self.actions.append('maximize')
    def restore(self): self.actions.append('restore')
    def destroy(self): self.actions.append('destroy')


def test_window_controls_are_restricted_to_local_management_page():
    controls = WindowControls('http://127.0.0.1:8765')
    window = FakeWindow('http://127.0.0.1:8765/long-image')
    controls._window = window
    controls.minimize()
    assert controls.toggle_maximize() is True
    assert controls.toggle_maximize() is False
    controls.close()
    assert window.actions == ['minimize', 'maximize', 'restore', 'destroy']
    window.url = 'https://example.com/'
    controls.minimize()
    assert controls.toggle_maximize() is False
    controls.close()
    assert window.actions == ['minimize', 'maximize', 'restore', 'destroy']


def test_native_window_styles_do_not_depend_on_service_asset_routes():
    class Window:
        def __init__(self): self.css = None; self.scripts = []
        def load_css(self, css): self.css = css
        def run_js(self, script): self.scripts.append(script)

    window = Window()
    install_native_assets(window)
    assert '.card{' in window.css
    assert any('data:image/svg+xml;base64,' in script for script in window.scripts)
    assert any('pywebviewready' in script for script in window.scripts)

