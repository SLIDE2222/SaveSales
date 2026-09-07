SaveSales LAN Fix
=================

WHY THE SECOND PC LOOKS EMPTY
The current SaveSales build can start its own local peer even when Windows Firewall prevents it from seeing the other PC. That is why the UI can say "LAN synced" while the second machine still has an empty local database.

IMMEDIATE FIX FOR THE INSTALL YOU ALREADY HAVE
1. Copy "Fix SaveSales LAN.bat" to both PCs.
2. Right-click it and choose "Run as administrator" on BOTH PCs.
3. Close SaveSales on both computers.
4. Start SaveSales on the PC that already contains the real store data first.
5. Start SaveSales on the second PC.
6. Keep both on the same router/Wi-Fi and wait about 5-10 seconds.

The firewall rules are restricted to the local subnet. The batch enables UDP 54545 for peer discovery and allows inbound SaveSales.exe traffic for the sync server's dynamically selected TCP port.

FOR FUTURE INSTALLERS
Replace your existing SaveSales.iss with the patched SaveSales.iss in this folder before compiling the installer. It automatically adds the same firewall rules during installation and removes them on uninstall.

DATA SAFETY
Do NOT delete %LOCALAPPDATA%\SaveSales on the PC that already contains your products/employees/sales. The existing SQLite data lives there and should be preserved across reinstallations.
