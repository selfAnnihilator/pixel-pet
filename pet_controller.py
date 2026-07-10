"""GTK4/Libadwaita settings surface for the Pixel Pet companion."""

from __future__ import annotations

import cairo
import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, Gtk, GLib

from pet_settings import set_launch_at_login


INPUT_GROUP_COMMAND = 'sudo usermod -aG input "$USER"'


class PetController:
    def __init__(self, app, pet, store, tracker, keyboard, launcher_path,
                 apply_overlay_visibility):
        self.app = app
        self.pet = pet
        self.store = store
        self.tracker = tracker
        self.keyboard = keyboard
        self.launcher_path = launcher_path
        self.apply_overlay_visibility = apply_overlay_visibility
        self._syncing = False

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
        GLib.timeout_add(100, self._tick_preview)

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
        self.window.set_visible(False)
        return True

    def present(self):
        self.window.present()

    def _draw_preview(self, _area, cr, width, height):
        animations = Gtk.Settings.get_default().get_property("gtk-enable-animations")
        if self.pet.user_paused or not animations:
            sheet, state, frame = self.pet.sheet, "track", 0
        else:
            sheet, state = self.pet._active()
            frame = self.pet.frame
        pixbuf = sheet.frames[state][min(frame, len(sheet.frames[state]) - 1)]
        bbox = sheet.bboxes[state][min(frame, len(sheet.bboxes[state]) - 1)]
        padding = 20
        opaque_width = max(1, bbox[2] - bbox[0])
        desired_width = 105 * self.pet.size_percent / 100.0
        scale = max(0.5, min(
            desired_width / opaque_width,
            (width - padding * 2) / pixbuf.get_width(),
            (height - padding * 2) / pixbuf.get_height(),
        ))
        draw_w, draw_h = pixbuf.get_width() * scale, pixbuf.get_height() * scale
        x, y = round((width - draw_w) / 2), round((height - draw_h) / 2)
        cr.save()
        cr.translate(x, y)
        cr.scale(scale, scale)
        Gdk.cairo_set_source_pixbuf(cr, pixbuf, 0, 0)
        cr.get_source().set_filter(cairo.FILTER_NEAREST)
        cr.paint()
        cr.restore()

    def _tick_preview(self):
        self.preview.queue_draw()
        return True

    def _set_saved(self):
        self.save_icon.set_from_icon_name("emblem-ok-symbolic")
        self.save_label.set_label("Saved")
        self.save_label.set_tooltip_text(None)

    def _set_error(self, message, detail):
        self.save_icon.set_from_icon_name("dialog-warning-symbolic")
        self.save_label.set_label(message)
        self.save_label.set_tooltip_text(str(detail))

    def _save_and_apply(self, key, value, apply):
        old = self.store.get(key)
        try:
            saved = self.store.update(key, value)
            apply(saved)
            self._set_saved()
            return True
        except OSError as error:
            apply(old)
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
            self._save_and_apply("size_percent", value, self.pet.set_size_percent)

    def _update_hold_label(self):
        self.hold_value.set_label(f"{self.hold_scale.get_value():.1f} seconds")

    def _on_hold_changed(self, scale):
        value = round(scale.get_value() * 2) / 2
        self._update_hold_label()
        if not self._syncing:
            self._save_and_apply("typing_hold_seconds", value, self.pet.set_typing_hold)

    def _on_tracking_changed(self, row, _param):
        if not self._syncing:
            self._save_and_apply("pointer_tracking", row.get_active(),
                                 self.pet.set_pointer_tracking)

    def _on_typing_changed(self, row, _param):
        if not self._syncing:
            self._save_and_apply("typing_reactions", row.get_active(),
                                 self.pet.set_typing_enabled)

    def _on_autostart_changed(self, row, _param):
        if self._syncing:
            return
        enabled = row.get_active()
        previous = self.store.get("launch_at_login")
        try:
            set_launch_at_login(enabled, self.launcher_path)
            self.store.update("launch_at_login", enabled)
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
        if self._save_and_apply("paused", paused, self.pet.set_user_paused):
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
        if self._save_and_apply("position", None, lambda _value: self.pet.reset_position()):
            self.preview.queue_draw()

    def _copy_input_command(self, _button):
        Gdk.Display.get_default().get_clipboard().set(INPUT_GROUP_COMMAND)
        self.save_icon.set_from_icon_name("edit-copy-symbolic")
        self.save_label.set_label("Setup command copied")

    def _recheck_permissions(self, _button):
        self.tracker.start()
        self.keyboard.start()
        self._refresh_permissions()

    def _refresh_permissions(self):
        missing = not self.tracker.available or not self.keyboard.available
        self.permission_group.set_visible(missing)
        self.tracking_row.set_sensitive(self.tracker.available)
        self.typing_row.set_sensitive(self.keyboard.available)
        if not missing:
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
            set_launch_at_login(False, self.launcher_path)
            self.store.reset()
            self._apply_all_settings()
            self._sync_controls()
            self._set_saved()
        except OSError as error:
            try:
                set_launch_at_login(previous_autostart, self.launcher_path)
            except OSError:
                pass
            self._set_error("Couldn’t restore defaults", error)

    def _apply_all_settings(self):
        self.pet.set_size_percent(self.store.get("size_percent"))
        self.pet.set_pointer_tracking(self.store.get("pointer_tracking"))
        self.pet.set_typing_enabled(self.store.get("typing_reactions"))
        self.pet.set_typing_hold(self.store.get("typing_hold_seconds"))
        self.pet.set_user_paused(self.store.get("paused"))
        self.pet.reset_position()
        self.apply_overlay_visibility()
        self._refresh_pause_ui()

    def _sync_controls(self):
        self._syncing = True
        self.size_scale.set_value(self.store.get("size_percent"))
        self.hold_scale.set_value(self.store.get("typing_hold_seconds"))
        self.tracking_row.set_active(self.store.get("pointer_tracking"))
        self.typing_row.set_active(self.store.get("typing_reactions"))
        self.autostart_row.set_active(self.store.get("launch_at_login"))
        self._syncing = False
        self._update_size_label()
        self._update_hold_label()
