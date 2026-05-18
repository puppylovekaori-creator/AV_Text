using System.Runtime.InteropServices;
using System.Text;

namespace AVTextInputPad;

internal static class NativeWindowHelper
{
    private const int SwRestore = 9;

    public static bool FocusFirstWindowContaining(string token)
    {
        var match = FindFirstWindowContaining(token);
        if (match == IntPtr.Zero)
        {
            return false;
        }

        ShowWindow(match, SwRestore);
        SetForegroundWindow(match);
        BringWindowToTop(match);
        return true;
    }

    public static IntPtr FindFirstWindowContaining(string token)
    {
        if (string.IsNullOrWhiteSpace(token))
        {
            return IntPtr.Zero;
        }

        IntPtr found = IntPtr.Zero;
        EnumWindows((hwnd, _) =>
        {
            if (!IsWindowVisible(hwnd))
            {
                return true;
            }

            var length = GetWindowTextLength(hwnd);
            if (length <= 0)
            {
                return true;
            }

            var buffer = new StringBuilder(length + 1);
            GetWindowText(hwnd, buffer, buffer.Capacity);
            var title = buffer.ToString();
            if (title.Contains(token, StringComparison.Ordinal))
            {
                found = hwnd;
                return false;
            }

            return true;
        }, IntPtr.Zero);

        return found;
    }

    private delegate bool EnumWindowsProc(IntPtr hwnd, IntPtr lParam);

    [DllImport("user32.dll")]
    private static extern bool EnumWindows(EnumWindowsProc lpEnumFunc, IntPtr lParam);

    [DllImport("user32.dll")]
    private static extern bool IsWindowVisible(IntPtr hWnd);

    [DllImport("user32.dll", CharSet = CharSet.Unicode)]
    private static extern int GetWindowText(IntPtr hWnd, StringBuilder lpString, int nMaxCount);

    [DllImport("user32.dll", CharSet = CharSet.Unicode)]
    private static extern int GetWindowTextLength(IntPtr hWnd);

    [DllImport("user32.dll")]
    private static extern bool ShowWindow(IntPtr hWnd, int nCmdShow);

    [DllImport("user32.dll")]
    private static extern bool SetForegroundWindow(IntPtr hWnd);

    [DllImport("user32.dll")]
    private static extern bool BringWindowToTop(IntPtr hWnd);
}
