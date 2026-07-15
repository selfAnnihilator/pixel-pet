"""GTK4/Libadwaita settings surface for the Pixel Pet companion."""

from __future__ import annotations

import cairo
import gi
import os
import subprocess
import sys
import threading
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, Gtk, GLib

from pet_settings import DEFAULTS, set_launch_at_login


INPUT_GROUP_COMMAND = 'sudo usermod -aG input "$USER"'


class PetController:
    def __init__(self, app, pet, store, live_settings, activity_input, launcher_path,
                 apply_overlay_visibility, refresh_presentation):
        self.app = app
        self.pet = pet
        self.store = store
        self.live_settings = live_settings
        self.activity_input = activity_input
        self.launcher_path = launcher_path
        self.apply_overlay_visibility = apply_overlay_visibility
        self.refresh_presentation = refresh_presentation
        self._syncing = False
        self._latest_snapshot = self.pet.behavior.snapshot()
        self._preview_plan = None
        self._preview_viewport = None

        self.window = Adw.ApplicationWindow(application=app, title="Pixel Pet")
        self.window.set_default_size(760, 560)
        self.window.set_size_request(520, 480)
        self.window.connect("close-request", self._on_close)

        toolbar = Adw.ToolbarView()
        toolbar.add_top_bar(Adw.HeaderBar())
        self.window.set_content(toolbar)

        self.main_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        self.main_box.add_css_class("controller-body")
        toolbar.set_content(self.main_box)

        self.preview_pane = self._build_preview()
        self.preview_pane.set_size_request(288, -1)
        self.main_box.append(self.preview_pane)

        separator = Gtk.Separator(orientation=Gtk.Orientation.VERTICAL)
        separator.add_css_class("main-separator")
        self.main_box.append(separator)

        scroller = Gtk.ScrolledWindow()
        scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroller.set_hexpand(True)
        scroller.set_vexpand(True)
        scroller.set_child(self._build_settings())
        self.main_box.append(scroller)

        toolbar.add_bottom_bar(self._build_footer())

        breakpoint = Adw.Breakpoint.new(
            Adw.BreakpointCondition.parse("max-width: 650sp")
        )
        breakpoint.add_setter(self.main_box, "orientation", Gtk.Orientation.VERTICAL)
        breakpoint.add_setter(self.preview_pane, "height-request", 260)
        breakpoint.add_setter(self.preview_pane, "width-request", -1)
        breakpoint.add_setter(separator, "orientation", Gtk.Orientation.HORIZONTAL)
        self.window.add_breakpoint(breakpoint)

        self._refresh_permissions()
        self._refresh_pause_ui()
        if self.store.first_run:
            self.save_icon.set_from_icon_name("dialog-information-symbolic")
            self.save_label.set_label("Changes save automatically")
        self.live_settings.set_listener(self._settings_status)

    def _build_preview(self):
        pane = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        pane.set_margin_top(24)
        pane.set_margin_bottom(24)
        pane.set_margin_start(24)
        pane.set_margin_end(24)
        pane.add_css_class("preview-pane")

        self.preview = Gtk.DrawingArea()
        self.preview.set_content_width(240)
        self.preview.set_content_height(270)
        self.preview.set_hexpand(True)
        self.preview.set_vexpand(True)
        self.preview.set_draw_func(self._draw_preview)
        self.preview.set_tooltip_text("Live preview of Catbone's current behavior")
        pane.append(self.preview)

        name = Gtk.Label(label="Catbone")
        name.set_xalign(0.5)
        name.add_css_class("title-1")
        pane.append(name)

        self.pet_status = Gtk.Label()
        self.pet_status.add_css_class("pet-status")
        pane.append(self.pet_status)

        description = Gtk.Label(label="A calm companion that reacts as you work.")
        description.set_wrap(True)
        description.set_justify(Gtk.Justification.CENTER)
        description.add_css_class("dim-label")
        pane.append(description)

        self.pause_button = Gtk.Button()
        self.pause_button.set_halign(Gtk.Align.CENTER)
        self.pause_button.set_size_request(180, 44)
        self.pause_button.connect("clicked", self._on_pause)
        pane.append(self.pause_button)
        return pane

    def _build_settings(self):
        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=24)
        content.set_margin_top(24)
        content.set_margin_bottom(24)
        content.set_margin_start(28)
        content.set_margin_end(28)

        self.permission_group = Adw.PreferencesGroup(title="Input access needed")
        permission_row = Adw.ActionRow(
            title="Tracking and typing need access to input devices",
            subtitle="Add your account to the input group, sign out, then sign back in.",
        )
        copy_button = Gtk.Button(label="Copy setup command")
        copy_button.set_valign(Gtk.Align.CENTER)
        copy_button.connect("clicked", self._copy_input_command)
        permission_row.add_suffix(copy_button)
        recheck_button = Gtk.Button(label="Recheck")
        recheck_button.set_valign(Gtk.Align.CENTER)
        recheck_button.connect("clicked", self._recheck_permissions)
        permission_row.add_suffix(recheck_button)
        self.permission_group.add(permission_row)
        content.append(self.permission_group)

        behavior = Adw.PreferencesGroup(title="Companion")

        size_row = Adw.ActionRow(title="Pet Size", subtitle="75% to 200%")
        size_box = Gtk.Box(spacing=12)
        self.size_scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 75, 200, 25)
        self.size_scale.set_value(self.store.get("size_percent"))
        self.size_scale.set_draw_value(False)
        self.size_scale.set_size_request(180, -1)
        self.size_scale.set_hexpand(True)
        self.size_scale.set_tooltip_text("Pet size from 75% to 200%")
        self.size_value = Gtk.Label(width_chars=5, xalign=1)
        size_box.append(self.size_scale)
        size_box.append(self.size_value)
        size_row.add_suffix(size_box)
        size_row.set_activatable_widget(self.size_scale)
        behavior.add(size_row)

        self.tracking_row = Adw.SwitchRow(
            title="Pointer Tracking", subtitle="Looks toward your pointer"
        )
        self.tracking_row.set_active(self.store.get("pointer_tracking"))
        behavior.add(self.tracking_row)

        self.typing_row = Adw.SwitchRow(
            title="Typing Reactions", subtitle="Types when you press keys"
        )
        self.typing_row.set_active(self.store.get("typing_reactions"))
        behavior.add(self.typing_row)

        self.petting_row = Adw.SwitchRow(
            title="Petting Reactions",
            subtitle="Rub Catbone's head to pet",
        )
        self.petting_row.set_active(self.store.get("petting_reactions"))
        behavior.add(self.petting_row)

        hold_row = Adw.ActionRow(
            title="Typing Hold", subtitle="Wait before sitting again"
        )
        hold_box = Gtk.Box(spacing=12)
        self.hold_scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 5, 0.5)
        self.hold_scale.set_value(self.store.get("typing_hold_seconds"))
        self.hold_scale.set_draw_value(False)
        self.hold_scale.set_size_request(150, -1)
        self.hold_scale.set_hexpand(True)
        self.hold_scale.set_tooltip_text("Typing hold from 0 to 5 seconds")
        self.hold_value = Gtk.Label(width_chars=9, xalign=1)
        hold_box.append(self.hold_scale)
        hold_box.append(self.hold_value)
        hold_row.add_suffix(hold_box)
        hold_row.set_activatable_widget(self.hold_scale)
        behavior.add(hold_row)
        content.append(behavior)

        system = Adw.PreferencesGroup(title="System")
        self.autostart_row = Adw.SwitchRow(
            title="Launch at Login", subtitle="Start Pixel Pet automatically"
        )
        self.autostart_row.set_active(self.store.get("launch_at_login"))
        system.add(self.autostart_row)

        update_row = Adw.ActionRow(
            title="Software Updates",
            subtitle="Install the latest stable GitHub Release",
        )
        self.update_button = Gtk.Button(label="Check and update")
        self.update_button.set_valign(Gtk.Align.CENTER)
        self.update_button.connect("clicked", self._on_update)
        update_row.add_suffix(self.update_button)
        update_row.set_activatable_widget(self.update_button)
        system.add(update_row)

        reset_row = Adw.ActionRow(
            title="Reset Position", subtitle="Return Catbone to the default spot"
        )
        reset_button = Gtk.Button(label="Reset position")
        reset_button.set_valign(Gtk.Align.CENTER)
        reset_button.connect("clicked", self._on_reset_position)
        reset_row.add_suffix(reset_button)
        reset_row.set_activatable_widget(reset_button)
        system.add(reset_row)
        content.append(system)

        self._update_size_label()
        self._update_hold_label()
        self.size_scale.connect("value-changed", self._on_size_changed)
        self.hold_scale.connect("value-changed", self._on_hold_changed)
        self.tracking_row.connect("notify::active", self._on_tracking_changed)
        self.typing_row.connect("notify::active", self._on_typing_changed)
        self.petting_row.connect("notify::active", self._on_petting_changed)
        self.autostart_row.connect("notify::active", self._on_autostart_changed)
        return content

    def _build_footer(self):
        bar = Gtk.ActionBar()
        status_box = Gtk.Box(spacing=8)
        self.save_icon = Gtk.Image.new_from_icon_name("emblem-ok-symbolic")
        self.save_label = Gtk.Label(label="Saved")
        status_box.append(self.save_icon)
        status_box.append(self.save_label)
        bar.pack_start(status_box)

        restore = Gtk.Button(label="Restore defaults")
        restore.connect("clicked", self._confirm_restore_defaults)
        bar.pack_end(restore)

        quit_button = Gtk.Button(label="Quit Pixel Pet")
        quit_button.add_css_class("destructive-action")
        quit_button.connect("clicked", lambda *_: self.app.quit())
        bar.pack_end(quit_button)
        return bar

    def _on_close(self, _window):
        try:
            self.live_settings.flush()
        except OSError as error:
            self._set_error("Couldn’t save settings", error)
            return True
        self.window.set_visible(False)
        return True

    def present(self):
        self.window.present()
        GLib.idle_add(self._refresh_after_present)

    def _refresh_after_present(self):
        self.refresh_presentation()
        return False

    def _draw_preview(self, _area, cr, width, height):
        if self._preview_plan is None or self._preview_viewport != (width, height):
            self._preview_viewport = (width, height)
            self._preview_plan = self.pet.preview_plan(
                width, height, self._latest_snapshot
            )
        plan = self._preview_plan
        self.pet.draw_plan(cr, plan)

    def refresh_snapshot(self, snapshot, *, force=False):
        self._latest_snapshot = snapshot
        if not self.window.get_visible():
            return
        width, height = self.preview.get_width(), self.preview.get_height()
        if width <= 1 or height <= 1:
            return
        plan = self.pet.preview_plan(width, height, snapshot)
        if force or plan != self._preview_plan:
            self._preview_plan = plan
            self._preview_viewport = (width, height)
            self.preview.queue_draw()

    def _set_saved(self):
        self.save_icon.set_from_icon_name("emblem-ok-symbolic")
        self.save_label.set_label("Saved")
        self.save_label.set_tooltip_text(None)

    def _set_error(self, message, detail):
        self.save_icon.set_from_icon_name("dialog-warning-symbolic")
        self.save_label.set_label(message)
        self.save_label.set_tooltip_text(str(detail))

    def _settings_status(self, state, error):
        if state == "saving":
            self.save_icon.set_from_icon_name("document-save-symbolic")
            self.save_label.set_label("Saving…")
            self.save_label.set_tooltip_text(None)
        elif state == "saved":
            self._set_saved()
        else:
            self._sync_controls()
            self._refresh_pause_ui()
            self.apply_overlay_visibility()
            self._set_error("Couldn’t save settings", error)

    def _change_setting(self, key, value):
        try:
            self.live_settings.change(key, value)
            if key in {"pointer_tracking", "typing_reactions"}:
                self._refresh_permissions(mark_saved=False)
            return True
        except Exception as error:
            self._sync_controls()
            self._refresh_pause_ui()
            self.apply_overlay_visibility()
            self._set_error("Couldn’t save settings", error)
            return False

    def _update_size_label(self):
        self.size_value.set_label(f"{int(round(self.size_scale.get_value()))}%")

    def _on_size_changed(self, scale):
        value = int(round(scale.get_value() / 25) * 25)
        self._update_size_label()
        if not self._syncing:
            self._change_setting("size_percent", value)

    def _update_hold_label(self):
        self.hold_value.set_label(f"{self.hold_scale.get_value():.1f} seconds")

    def _on_hold_changed(self, scale):
        value = round(scale.get_value() * 2) / 2
        self._update_hold_label()
        if not self._syncing:
            self._change_setting("typing_hold_seconds", value)

    def _on_tracking_changed(self, row, _param):
        if not self._syncing:
            self._change_setting("pointer_tracking", row.get_active())

    def _on_typing_changed(self, row, _param):
        if not self._syncing:
            self._change_setting("typing_reactions", row.get_active())

    def _on_petting_changed(self, row, _param):
        if not self._syncing:
            self._change_setting("petting_reactions", row.get_active())

    def _on_autostart_changed(self, row, _param):
        if self._syncing:
            return
        enabled = row.get_active()
        previous = self.store.get("launch_at_login")
        try:
            self.live_settings.flush()
            set_launch_at_login(enabled, self.launcher_path)
            self.store.update("launch_at_login", enabled)
            self.live_settings.accept_durable(self.store.data)
            self._set_saved()
        except OSError as error:
            try:
                set_launch_at_login(previous, self.launcher_path)
            except OSError:
                pass
            self._syncing = True
            row.set_active(previous)
            self._syncing = False
            self._set_error("Couldn’t update launch at login", error)

    def _on_pause(self, _button):
        paused = not self.pet.user_paused
        if self._change_setting("paused", paused):
            self.apply_overlay_visibility()
            self._refresh_pause_ui()

    def _refresh_pause_ui(self):
        paused = self.pet.user_paused
        self.pause_button.set_label("Resume" if paused else "Pause")
        self.pet_status.set_label("● Paused" if paused else "● Active")
        self.pet_status.remove_css_class("paused-status")
        if paused:
            self.pet_status.add_css_class("paused-status")

    def _on_reset_position(self, _button):
        if self._change_setting("position", None):
            self.refresh_presentation()

    def _on_update(self, _button):
        self.update_button.set_sensitive(False)
        self.update_button.set_label("Checking…")
        manager = os.path.join(os.path.dirname(self.launcher_path), "pixel_pet_manager.py")

        def run_update():
            result = subprocess.run(
                [sys.executable, manager, "update"],
                capture_output=True,
                text=True,
            )
            GLib.idle_add(self._finish_update, result)

        threading.Thread(target=run_update, daemon=True).start()

    def _finish_update(self, result):
        self.update_button.set_sensitive(True)
        self.update_button.set_label("Check and update")
        output = (result.stdout if result.returncode == 0 else result.stderr).strip()
        if result.returncode == 0:
            title = "Update check complete"
            detail = output or "Pixel Pet is up to date."
        else:
            title = "Update failed"
            detail = output or "Could not check for updates."
        dialog = Adw.AlertDialog.new(title, detail)
        dialog.add_response("close", "Close")
        dialog.set_default_response("close")
        dialog.present(self.window)
        return False

    def _copy_input_command(self, _button):
        Gdk.Display.get_default().get_clipboard().set(INPUT_GROUP_COMMAND)
        self.save_icon.set_from_icon_name("edit-copy-symbolic")
        self.save_label.set_label("Setup command copied")

    def _recheck_permissions(self, _button):
        self.activity_input.recheck_access()
        self._refresh_permissions()

    def _refresh_permissions(self, *, mark_saved=True):
        missing = (
            not self.activity_input.pointer_available
            or not self.activity_input.keyboard_available
        )
        self.permission_group.set_visible(missing)
        self.tracking_row.set_sensitive(self.activity_input.pointer_available)
        self.typing_row.set_sensitive(self.activity_input.keyboard_available)
        if not missing and mark_saved:
            self._set_saved()

    def _confirm_restore_defaults(self, _button):
        dialog = Adw.AlertDialog.new(
            "Restore default settings?",
            "Your pet size, reactions, position, and launch preference will be reset.",
        )
        dialog.add_response("keep", "Keep current settings")
        dialog.add_response("restore", "Restore defaults")
        dialog.set_response_appearance("restore", Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.set_default_response("keep")
        dialog.set_close_response("keep")
        dialog.choose(self.window, None, self._finish_restore_defaults)

    def _finish_restore_defaults(self, dialog, result):
        if dialog.choose_finish(result) != "restore":
            return
        previous_autostart = self.store.get("launch_at_login")
        try:
            self.live_settings.flush()
            set_launch_at_login(False, self.launcher_path)
            self.live_settings.replace(DEFAULTS)
            self.live_settings.flush()
            self._sync_controls()
            self._refresh_permissions()
            self._refresh_pause_ui()
            self.apply_overlay_visibility()
            self._set_saved()
        except OSError as error:
            try:
                set_launch_at_login(previous_autostart, self.launcher_path)
            except OSError:
                pass
            self._set_error("Couldn’t restore defaults", error)

    def _sync_controls(self):
        self._syncing = True
        self.size_scale.set_value(self.store.get("size_percent"))
        self.hold_scale.set_value(self.store.get("typing_hold_seconds"))
        self.tracking_row.set_active(self.store.get("pointer_tracking"))
        self.typing_row.set_active(self.store.get("typing_reactions"))
        self.petting_row.set_active(self.store.get("petting_reactions"))
        self.autostart_row.set_active(self.store.get("launch_at_login"))
        self._syncing = False
        self._update_size_label()
        self._update_hold_label()
