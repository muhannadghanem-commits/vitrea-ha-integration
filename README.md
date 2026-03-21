# Vitrea Smart Home Integration for Home Assistant

Custom integration for Vitrea Smart Home (VBox Pro controller) via local TCP connection on port 11501.

## Features
- Light control (on/off + brightness)
- Cover/blind control (open/close/position)
- Real-time push state updates
- UI-based config flow

## Installation via HACS
1. HACS → Integrations → Custom repositories
2. Add: `https://github.com/muhannadghanem-commits/vitrea-ha-integration`
3. Category: Integration
4. Download and restart HA

## Configuration
1. Settings → Integrations → Add Integration → "Vitrea Smart Home"
2. Enter VBox Pro IP, port (11501), username, password
