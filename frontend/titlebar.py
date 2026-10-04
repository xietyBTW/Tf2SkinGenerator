"""
Свой заголовок окна вместо системного.

Окно остаётся обычным окном Windows: изменение размера за края, прилипание к
краям экрана, Win+стрелки, тень и скругления Windows 11 работают как у всех
окон. Убирается только полоса заголовка: окно отдаёт её место странице
(WM_NCCALCSIZE). Таскают окно за шапку страницы средствами самого WebView2
(CSS `app-region: drag`): двойной щелчок разворачивает, правый открывает
системное меню. Кнопки «свернуть / развернуть / закрыть» рисует страница
(titlebar.js) и зовёт сюда через api.window_control.

Края. Слева, справа и снизу рамка изменения размера остаётся системной: это
невидимая полоса за видимым краем окна. Сверху её место заняла страница, а
WebView2 забирает себе все щелчки над ней. Поэтому над ним оставлена полоска
формы в несколько пикселей цвета фона: на ней окно отвечает «здесь верхний
край» (WM_NCHITTEST). У развёрнутого окна полоски нет: кнопки окна должны
доставать до края экрана.

Без поддержки перетаскивания в WebView2 окно без заголовка нельзя было бы
сдвинуть, поэтому тогда системный заголовок возвращается.
"""

from __future__ import annotations

import ctypes
import logging
from ctypes import wintypes

logger = logging.getLogger(__name__)

#: Фон страницы по темам (--bg из base.css, передаёт app.py): полоска над
#: WebView2 не должна выделяться.
_colors: dict = {}

#: Высота полоски под верхний край окна, логические пиксели.
TOP_GRIP = 4

_ID = 1
_WM_SYSCOMMAND = 0x0112
_SC_MINIMIZE, _SC_MAXIMIZE, _SC_RESTORE, _SC_CLOSE = 0xF020, 0xF030, 0xF120, 0xF060
_WM_WINDOWPOSCHANGING = 0x0046
_WM_WINDOWPOSCHANGED = 0x0047
_SWP_NOSIZE = 0x0001
_WM_NCDESTROY = 0x0082
_WM_NCCALCSIZE = 0x0083
_WM_NCHITTEST = 0x0084
_HTCLIENT, _HTTOP, _HTTOPLEFT, _HTTOPRIGHT = 1, 12, 13, 14
_SM_CYSIZEFRAME, _SM_CXPADDEDBORDER = 33, 92
# NOSIZE | NOMOVE | NOZORDER | NOACTIVATE | FRAMECHANGED | NOOWNERZORDER
_SWP_FRAME = 0x0001 | 0x0002 | 0x0004 | 0x0010 | 0x0020 | 0x0200
_DWMWA_USE_IMMERSIVE_DARK_MODE = 20

_LRESULT = ctypes.c_ssize_t
_SUBCLASSPROC = ctypes.WINFUNCTYPE(_LRESULT, wintypes.HWND, wintypes.UINT,
                                   wintypes.WPARAM, wintypes.LPARAM,
                                   ctypes.c_size_t, ctypes.c_size_t)


class _NCCALCSIZE_PARAMS(ctypes.Structure):
    _fields_ = [('rgrc', wintypes.RECT * 3), ('lppos', ctypes.c_void_p)]


class _WINDOWPOS(ctypes.Structure):
    _fields_ = [('hwnd', wintypes.HWND), ('hwndInsertAfter', wintypes.HWND),
                ('x', ctypes.c_int), ('y', ctypes.c_int),
                ('cx', ctypes.c_int), ('cy', ctypes.c_int), ('flags', wintypes.UINT)]


class _APPBARDATA(ctypes.Structure):
    _fields_ = [('cbSize', wintypes.DWORD), ('hWnd', wintypes.HWND),
                ('uCallbackMessage', wintypes.UINT), ('uEdge', wintypes.UINT),
                ('rc', wintypes.RECT), ('lParam', wintypes.LPARAM)]


class _MONITORINFO(ctypes.Structure):
    _fields_ = [('cbSize', wintypes.DWORD), ('rcMonitor', wintypes.RECT),
                ('rcWork', wintypes.RECT), ('dwFlags', wintypes.DWORD)]


# Самопрячущаяся панель задач: её состояние и края (shellapi.h).
_ABM_GETSTATE, _ABM_GETAUTOHIDEBAREX = 0x04, 0x0B
_ABS_AUTOHIDE = 0x01
_ABE_LEFT, _ABE_TOP, _ABE_RIGHT, _ABE_BOTTOM = 0, 1, 2, 3
_MONITOR_DEFAULTTONEAREST = 2
#: Сколько пикселей оставить панели у её края, чтобы она могла выехать.
_AUTOHIDE_GAP = 2


_user32 = ctypes.WinDLL('user32')
_comctl32 = ctypes.WinDLL('comctl32')
_dwmapi = ctypes.WinDLL('dwmapi')
_shell32 = ctypes.WinDLL('shell32')

_comctl32.SetWindowSubclass.argtypes = [wintypes.HWND, _SUBCLASSPROC, ctypes.c_size_t, ctypes.c_size_t]
_comctl32.SetWindowSubclass.restype = wintypes.BOOL
_comctl32.RemoveWindowSubclass.argtypes = [wintypes.HWND, _SUBCLASSPROC, ctypes.c_size_t]
_comctl32.RemoveWindowSubclass.restype = wintypes.BOOL
_comctl32.DefSubclassProc.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
_comctl32.DefSubclassProc.restype = _LRESULT
_user32.GetDpiForWindow.argtypes = [wintypes.HWND]
_user32.GetDpiForWindow.restype = wintypes.UINT
_user32.GetSystemMetricsForDpi.argtypes = [ctypes.c_int, wintypes.UINT]
_user32.GetSystemMetricsForDpi.restype = ctypes.c_int
_user32.IsZoomed.argtypes = [wintypes.HWND]
_user32.IsZoomed.restype = wintypes.BOOL
_user32.IsIconic.argtypes = [wintypes.HWND]
_user32.IsIconic.restype = wintypes.BOOL
_user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
_user32.GetWindowRect.restype = wintypes.BOOL
_user32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int,
                                 ctypes.c_int, ctypes.c_int, wintypes.UINT]
_user32.SetWindowPos.restype = wintypes.BOOL
_user32.SendMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
_user32.SendMessageW.restype = _LRESULT
_user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
_user32.PostMessageW.restype = wintypes.BOOL
_dwmapi.DwmSetWindowAttribute.argtypes = [wintypes.HWND, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD]
_shell32.SHAppBarMessage.argtypes = [wintypes.DWORD, ctypes.POINTER(_APPBARDATA)]
_shell32.SHAppBarMessage.restype = ctypes.c_size_t
_user32.MonitorFromWindow.argtypes = [wintypes.HWND, wintypes.DWORD]
_user32.MonitorFromWindow.restype = wintypes.HMONITOR
_user32.GetMonitorInfoW.argtypes = [wintypes.HMONITOR, ctypes.POINTER(_MONITORINFO)]
_user32.GetMonitorInfoW.restype = wintypes.BOOL

#: Окно со своим заголовком: (pywebview-окно, его HWND). Пусто — заголовок системный.
_active: dict = {}

#: Состояние окна при прошлом перемещении и размер, который держим, пока
#: WinForms возвращает окно в обычное состояние (см. _wndproc).
_shown = {'state': 'normal', 'hold': None}


def _scaled(hwnd, logical: int) -> int:
    return round(logical * (_user32.GetDpiForWindow(hwnd) or 96) / 96)


def _frame(hwnd) -> int:
    """Толщина рамки изменения размера в физических пикселях."""
    dpi = _user32.GetDpiForWindow(hwnd) or 96
    return (_user32.GetSystemMetricsForDpi(_SM_CYSIZEFRAME, dpi)
            + _user32.GetSystemMetricsForDpi(_SM_CXPADDEDBORDER, dpi))


def _top_edge(hwnd, lparam: int) -> int:
    """
    Код верхнего края под курсором или 0.

    Над WebView2 окно этого сообщения не получает (его забирает WebView2),
    так что «клиентская» точка окна — это и есть полоска. Высоту сверяем с
    запасом: WinForms при запуске может ещё раз отмасштабировать отступ.
    """
    x = ctypes.c_short(lparam & 0xFFFF).value
    y = ctypes.c_short((lparam >> 16) & 0xFFFF).value
    rect = wintypes.RECT()
    _user32.GetWindowRect(hwnd, ctypes.byref(rect))
    if y >= rect.top + 3 * _scaled(hwnd, TOP_GRIP):
        return 0
    corner = 2 * _frame(hwnd)
    if x < rect.left + corner:
        return _HTTOPLEFT
    if x >= rect.right - corner:
        return _HTTOPRIGHT
    return _HTTOP


def _autohide_edges(hwnd) -> list:
    """Края монитора окна, у которых прячется панель задач."""
    state = _APPBARDATA(cbSize=ctypes.sizeof(_APPBARDATA))
    if not _shell32.SHAppBarMessage(_ABM_GETSTATE, ctypes.byref(state)) & _ABS_AUTOHIDE:
        return []
    info = _MONITORINFO(cbSize=ctypes.sizeof(_MONITORINFO))
    monitor = _user32.MonitorFromWindow(hwnd, _MONITOR_DEFAULTTONEAREST)
    if not monitor or not _user32.GetMonitorInfoW(monitor, ctypes.byref(info)):
        return []
    edges = []
    for edge in (_ABE_LEFT, _ABE_TOP, _ABE_RIGHT, _ABE_BOTTOM):
        bar = _APPBARDATA(cbSize=ctypes.sizeof(_APPBARDATA), uEdge=edge, rc=info.rcMonitor)
        if _shell32.SHAppBarMessage(_ABM_GETAUTOHIDEBAREX, ctypes.byref(bar)):
            edges.append(edge)
    return edges


def _client_rect(hwnd, rect, top: int) -> None:
    """
    Клиентская область после системного расчёта рамки.

    Бока и низ рамка оставила себе, верх отдаём странице. Развёрнутое окно
    выходит за экран на толщину рамки: без поправки шапка уехала бы за
    верхний край монитора. А если панель задач прячется сама, развёрнутое окно
    не должно закрывать монитор целиком: оболочка сочтёт его полноэкранным, и
    панель перестанет выезжать (на этом спотыкались Windows Terminal и Chromium).
    """
    if not _user32.IsZoomed(hwnd):
        rect.top = top
        return
    rect.top = top + _frame(hwnd)
    for edge in _autohide_edges(hwnd):
        if edge == _ABE_LEFT:
            rect.left += _AUTOHIDE_GAP
        elif edge == _ABE_TOP:
            rect.top += _AUTOHIDE_GAP
        elif edge == _ABE_RIGHT:
            rect.right -= _AUTOHIDE_GAP
        else:
            rect.bottom -= _AUTOHIDE_GAP


def _restore_hold(hwnd):
    """
    Размер, который надо удержать на этом перемещении, или None.

    Уходя из обычного состояния, WinForms запоминает размер клиентской области,
    а возвращаясь, пересчитывает по нему окно — так, будто заголовок на месте:
    каждое «развернуть — свернуть в окно» растило окно на его высоту. Пока
    WinForms это делает (вложенно, внутри перемещения), держим размер, который
    уже вернула сама Windows.
    """
    now = ('max' if _user32.IsZoomed(hwnd)
           else 'min' if _user32.IsIconic(hwnd) else 'normal')
    prev, _shown['state'] = _shown['state'], now
    if prev == 'normal' or now != 'normal':
        return None
    rect = wintypes.RECT()
    _user32.GetWindowRect(hwnd, ctypes.byref(rect))
    return (rect.right - rect.left, rect.bottom - rect.top)


@_SUBCLASSPROC
def _wndproc(hwnd, msg, wparam, lparam, _id, _data):
    # Ошибка в своей поправке не должна ломать окно: каждая ветка в худшем
    # случае оставляет системный ответ как есть.
    if msg == _WM_NCCALCSIZE and wparam:
        params = _NCCALCSIZE_PARAMS.from_address(lparam)
        top = params.rgrc[0].top
        res = _comctl32.DefSubclassProc(hwnd, msg, wparam, lparam)
        if res == 0:
            try:
                _client_rect(hwnd, params.rgrc[0], top)
            except Exception:                 # noqa: BLE001
                logger.exception("свой заголовок окна: WM_NCCALCSIZE")
        return res
    if msg == _WM_WINDOWPOSCHANGING and _shown['hold']:
        pos = _WINDOWPOS.from_address(lparam)
        if not pos.flags & _SWP_NOSIZE:
            pos.cx, pos.cy = _shown['hold']
    if msg == _WM_WINDOWPOSCHANGED:
        try:
            hold = _restore_hold(hwnd)
        except Exception:                     # noqa: BLE001
            logger.exception("свой заголовок окна: WM_WINDOWPOSCHANGED")
            hold = None
        if hold:
            _shown['hold'] = hold
            try:
                return _comctl32.DefSubclassProc(hwnd, msg, wparam, lparam)
            finally:
                _shown['hold'] = None
    res = _comctl32.DefSubclassProc(hwnd, msg, wparam, lparam)
    if msg == _WM_NCHITTEST and res == _HTCLIENT and not _user32.IsZoomed(hwnd):
        try:
            return _top_edge(hwnd, lparam) or res
        except Exception:                     # noqa: BLE001
            logger.exception("свой заголовок окна: WM_NCHITTEST")
    if msg == _WM_NCDESTROY:
        _comctl32.RemoveWindowSubclass(hwnd, _wndproc, _ID)
        # Окна больше нет, а номер его может достаться другому: кнопки
        # страницы не должны слать ему команды.
        _active.pop('window', None)
    return res


def _form(window):
    from webview.platforms.winforms import BrowserView
    return BrowserView.instances.get(window.uid)


def _set_grip(form, hwnd) -> None:
    """Полоска над WebView2 под верхний край; у развёрнутого окна её нет."""
    from System.Windows.Forms import Padding
    form.Padding = Padding(0, 0 if _user32.IsZoomed(hwnd) else _scaled(hwnd, TOP_GRIP), 0, 0)


def _set_theme(form, hwnd, theme: str) -> None:
    """Цвет полоски и тёмная рамка окна — под тему страницы."""
    from System.Drawing import ColorTranslator
    form.BackColor = ColorTranslator.FromHtml(_colors.get(theme) or _colors['dark'])
    dark = ctypes.c_int(1 if theme == 'dark' else 0)
    _dwmapi.DwmSetWindowAttribute(hwnd, _DWMWA_USE_IMMERSIVE_DARK_MODE,
                                  ctypes.byref(dark), ctypes.sizeof(dark))


def _on_ui(form, fn) -> None:
    """Выполняет fn в потоке окна: формой можно пользоваться только оттуда."""
    from System import Action
    form.Invoke(Action(fn))


def _remove(window) -> None:
    """Возвращает системный заголовок (зовётся в потоке окна)."""
    item = _active.pop('window', None)
    if item is None:
        return
    form, hwnd = _form(window), item[1]
    _comctl32.RemoveWindowSubclass(hwnd, _wndproc, _ID)
    if form is not None:
        from System.Windows.Forms import Padding
        form.Padding = Padding(0)
    _user32.SetWindowPos(hwnd, None, 0, 0, 0, 0, _SWP_FRAME)


def _enable_app_region(window) -> bool:
    """
    Включает в WebView2 CSS app-region: перетаскивание окна за шапку.

    Настройка действует со следующей навигации, а первую pywebview начинает
    сразу по готовности WebView2. Поэтому ставим её раньше него: подменяем
    его обработчик готовности до того, как окно его подпишет. Без этой
    настройки окно без заголовка не сдвинуть — тогда заголовок возвращается.
    """
    try:
        from webview.platforms import edgechromium
        ready = edgechromium.EdgeChrome.on_webview_ready
    except Exception as exc:                  # noqa: BLE001 — нет WebView2 / другая версия
        logger.warning(f"свой заголовок окна: нет WebView2 ({exc})")
        return False

    def on_webview_ready(self, sender, args):
        # Не поднялся WebView2 (CoreWebView2 тогда пуст) или он слишком стар
        # для этой настройки — окно без заголовка нельзя было бы ни сдвинуть,
        # ни развернуть. Возвращаем системный.
        try:
            sender.CoreWebView2.Settings.IsNonClientRegionSupportEnabled = True
        except Exception as exc:              # noqa: BLE001
            logger.warning(f"свой заголовок окна: WebView2 не таскает окно ({exc})")
            try:
                _remove(window)
            except Exception:                 # noqa: BLE001
                logger.exception("свой заголовок окна: системный не вернулся")
        finally:
            ready(self, sender, args)

    edgechromium.EdgeChrome.on_webview_ready = on_webview_ready
    return True


def attach(window, theme: str, colors: dict) -> None:
    """Подключает свой заголовок к окну pywebview (до webview.start).

    `colors` — фон страницы по темам: им красится полоска над WebView2.
    """
    _colors.update(colors)
    if not _enable_app_region(window):
        return

    def before_show(window):
        # В потоке окна, форма создана и ещё не показана: системный заголовок
        # не успеет мелькнуть. Без WebView2 (pywebview откатился на старый
        # движок) таскать окно было бы нечем — тогда заголовок не трогаем.
        from webview.platforms import winforms
        if not getattr(winforms, 'is_chromium', False):
            logger.warning("свой заголовок окна: движок не WebView2, заголовок системный")
            return
        form = _form(window)
        hwnd = form.Handle.ToInt64()
        if not _comctl32.SetWindowSubclass(hwnd, _wndproc, _ID, 0):
            logger.warning("свой заголовок окна: окно не дало подписаться на сообщения")
            return
        _active['window'] = (window, hwnd)
        _set_grip(form, hwnd)
        _set_theme(form, hwnd, theme)
        _user32.SetWindowPos(hwnd, None, 0, 0, 0, 0, _SWP_FRAME)

    def resized(window):
        item = _active.get('window')
        form = _form(window)
        if item and form is not None:
            _on_ui(form, lambda: _set_grip(form, item[1]))

    window.events.before_show += before_show
    window.events.maximized += resized
    window.events.restored += resized


def control(action: str = '', theme: str = '') -> dict:
    """
    api.window_control: кнопки страницы → окно.

    Ответ — есть ли свой заголовок (`custom`) и развёрнуто ли окно: по нему
    страница показывает кнопки и рисует «развернуть» или «свернуть в окно».
    """
    item = _active.get('window')
    if item is None:
        return {'custom': False}
    window, hwnd = item
    # Те же команды, что шлют системные кнопки заголовка. WindowState формы
    # не годится: WinForms считает размер так, будто заголовок на месте, и
    # после «развернуть — свернуть в окно» окно вырастало на его высоту.
    if action == 'minimize':
        # Свёрнутое окно не «развёрнуто» для Windows, а страница после
        # возврата не узнает об этом сама (размер её не меняется). Отвечаем
        # тем, во что окно вернётся.
        was = bool(_user32.IsZoomed(hwnd))
        _user32.SendMessageW(hwnd, _WM_SYSCOMMAND, _SC_MINIMIZE, 0)
        return {'custom': True, 'maximized': was}
    elif action == 'maximize':
        command = _SC_RESTORE if _user32.IsZoomed(hwnd) else _SC_MAXIMIZE
        _user32.SendMessageW(hwnd, _WM_SYSCOMMAND, command, 0)
    elif action == 'close':
        # Как Alt+F4: закрытие идёт обычным путём окна, ответ не ждём.
        _user32.PostMessageW(hwnd, _WM_SYSCOMMAND, _SC_CLOSE, 0)
        return {'custom': True, 'maximized': False}
    elif action == 'theme':
        form = _form(window)
        if form is not None:
            _on_ui(form, lambda: _set_theme(form, hwnd, theme))
    return {'custom': True, 'maximized': bool(_user32.IsZoomed(hwnd))}
