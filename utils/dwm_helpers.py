import ctypes


def remove_dwm_border(hwnd: int):
    """Use Windows DWM API to remove the shadow/border around a window."""
    try:
        dwmapi = ctypes.windll.dwmapi
        user32 = ctypes.windll.user32

        # DWMWA_NCRENDERING_POLICY = 2, DWMNCRP_DISABLED = 1
        policy = ctypes.c_int(1)
        dwmapi.DwmSetWindowAttribute(
            hwnd, 2, ctypes.byref(policy), ctypes.sizeof(policy)
        )

        # DWMWA_TRANSITIONS_FORCEDISABLED = 3
        disabled = ctypes.c_int(1)
        dwmapi.DwmSetWindowAttribute(
            hwnd, 3, ctypes.byref(disabled), ctypes.sizeof(disabled)
        )

        # Windows 11: set border colour to DWMWA_COLOR_NONE (0xFFFFFFFE)
        # DWMWA_BORDER_COLOR = 34
        color_none = ctypes.c_uint(0xFFFFFFFE)
        dwmapi.DwmSetWindowAttribute(
            hwnd, 34, ctypes.byref(color_none), ctypes.sizeof(color_none)
        )

        # Windows 11: disable rounded corners
        # DWMWA_WINDOW_CORNER_PREFERENCE = 33, DWMWCP_DONOTROUND = 1
        corner = ctypes.c_int(1)
        dwmapi.DwmSetWindowAttribute(
            hwnd, 33, ctypes.byref(corner), ctypes.sizeof(corner)
        )

        # Collapse the DWM frame to zero
        class MARGINS(ctypes.Structure):
            _fields_ = [
                ("cxLeftWidth", ctypes.c_int),
                ("cxRightWidth", ctypes.c_int),
                ("cyTopHeight", ctypes.c_int),
                ("cyBottomHeight", ctypes.c_int),
            ]
        margins = MARGINS(0, 0, 0, 0)
        dwmapi.DwmExtendFrameIntoClientArea(hwnd, ctypes.byref(margins))

        # Strip extended-style flags that can introduce borders
        GWL_EXSTYLE = -20
        WS_EX_DLGMODALFRAME = 0x0001
        WS_EX_CLIENTEDGE = 0x0200
        WS_EX_STATICEDGE = 0x00020000
        style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
        style &= ~(WS_EX_DLGMODALFRAME | WS_EX_CLIENTEDGE | WS_EX_STATICEDGE)
        user32.SetWindowLongW(hwnd, GWL_EXSTYLE, style)

        # Force the frame change to take effect
        SWP_FRAMECHANGED = 0x0020
        SWP_NOMOVE = 0x0002
        SWP_NOSIZE = 0x0001
        SWP_NOZORDER = 0x0004
        user32.SetWindowPos(
            hwnd, 0, 0, 0, 0, 0,
            SWP_FRAMECHANGED | SWP_NOMOVE | SWP_NOSIZE | SWP_NOZORDER,
        )
    except Exception:
        pass
