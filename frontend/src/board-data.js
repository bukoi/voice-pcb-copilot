// Mirrors backend/data/power_supply.json so the UI can show an at-a-glance
// reference panel without waiting on a round trip through the voice agent.
// If the board data changes on the backend, update this file to match.

export const BOARD = {
  name: "Power Supply PCB",
  description: "5V-to-3.3V regulated power supply, enable-controlled",
};

export const COMPONENTS = [
  { id: "U1", part: "LM1117-3.3", role: "Voltage regulator" },
  { id: "R1", part: "10k\u03A9", role: "EN pull-up" },
  { id: "R2", part: "1k\u03A9", role: "LED current limit" },
  { id: "C1", part: "10\u00B5F elec.", role: "Input filter" },
  { id: "C2", part: "100nF ceramic", role: "Output filter" },
  { id: "D1", part: "1N4007", role: "Reverse-polarity guard" },
  { id: "LED1", part: "3mm red", role: "Power indicator" },
  { id: "J1", part: "JST-2", role: "Power input" },
];

export const TEST_POINTS = [
  { id: "TP1", location: "U1 INPUT", expected: "5V" },
  { id: "TP2", location: "U1 ENABLE", expected: "3.3\u20135V" },
  { id: "TP3", location: "U1 OUTPUT", expected: "3.3V" },
  { id: "TP4", location: "GND", expected: "0V" },
];

// All reference designators the transcript parser watches for, longest
// first so "LED1" matches before a bare "1" or "L" ever could.
export const ALL_IDS = [...COMPONENTS, ...TEST_POINTS]
  .map((item) => item.id)
  .sort((a, b) => b.length - a.length);