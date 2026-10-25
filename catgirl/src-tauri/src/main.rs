#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use tauri::{
    menu::{Menu, MenuItem},
    tray::TrayIconBuilder,
    Emitter, Manager,
};

const WINDOW_LABEL: &str = "catgirl";
const RESTORE_EVENT: &str = "catgirl://restore";
const HIDE_EVENT: &str = "catgirl://hide";

fn restore_window(app: &tauri::AppHandle) {
    if let Some(window) = app.get_webview_window(WINDOW_LABEL) {
        let _ = window.emit(RESTORE_EVENT, ());
    }
}

fn toggle_window(app: &tauri::AppHandle) {
    let Some(window) = app.get_webview_window(WINDOW_LABEL) else {
        return;
    };
    if window.is_visible().unwrap_or(false) {
        let _ = window.emit(HIDE_EVENT, ());
    } else {
        restore_window(app);
    }
}

#[tauri::command]
fn quit_app(app: tauri::AppHandle) {
    app.exit(0);
}

#[tauri::command]
fn uses_fixed_surface() -> bool {
    cfg!(target_os = "linux")
}

#[cfg(target_os = "linux")]
fn apply_panel_input(
    window: &tauri::WebviewWindow,
    open: bool,
    sprite_size: i32,
) -> Result<(), String> {
    use gtk::prelude::WidgetExt;
    let gtk_window = window.gtk_window().map_err(|error| error.to_string())?;
    let gdk_window = gtk_window.window().ok_or("窗口尚未创建 GDK surface")?;
    let allocation = gtk_window.allocation();
    let (x, y, width, height) = if open {
        (0, 0, allocation.width(), allocation.height())
    } else {
        (
            allocation.width() - sprite_size,
            allocation.height() - sprite_size,
            sprite_size,
            sprite_size,
        )
    };
    let region =
        gtk::cairo::Region::create_rectangle(&gtk::cairo::RectangleInt::new(x, y, width, height));
    gdk_window.input_shape_combine_region(&region, 0, 0);
    Ok(())
}

#[tauri::command]
fn set_panel_input(
    window: tauri::WebviewWindow,
    open: bool,
    sprite_size: i32,
) -> Result<(), String> {
    #[cfg(target_os = "linux")]
    apply_panel_input(&window, open, sprite_size)?;
    #[cfg(not(target_os = "linux"))]
    let _ = (window, open, sprite_size);
    Ok(())
}

fn main() {
    tauri::Builder::default()
        .invoke_handler(tauri::generate_handler![
            quit_app,
            uses_fixed_surface,
            set_panel_input
        ])
        .on_window_event(|window, event| {
            if matches!(event, tauri::WindowEvent::Focused(true)) {
                let _ = window.set_always_on_top(true);
            }
        })
        // 单实例锁必须最先注册；二次启动只会把已有窗口带回前台
        .plugin(tauri_plugin_single_instance::init(|app, _args, _cwd| {
            restore_window(app);
        }))
        .setup(|app| {
            let toggle = MenuItem::with_id(app, "toggle", "显示 / 隐藏猫娘", true, None::<&str>)?;
            let quit = MenuItem::with_id(app, "quit", "退出", true, None::<&str>)?;
            let menu = Menu::with_items(app, &[&toggle, &quit])?;

            let mut tray = TrayIconBuilder::with_id("main")
                .menu(&menu)
                .show_menu_on_left_click(false)
                .tooltip("猫娘");
            if let Some(icon) = app.default_window_icon() {
                tray = tray.icon(icon.clone());
            }
            let _tray = tray
                .on_menu_event(|app, event| match event.id().as_ref() {
                    "toggle" => toggle_window(app),
                    "quit" => app.exit(0),
                    _ => {}
                })
                .build(app)?;

            Ok(())
        })
        .run(tauri::generate_context!())
        .expect("猫娘启动失败");
}
