/**
 * game-colors.js — PGM / Minecraft color palettes used across the editor.
 *
 * Two palettes:
 *   PGM_CHAT_COLORS      — the `color` attribute on a <team> element.
 *                          Standard Minecraft chat-color values.
 *   MINECRAFT_DYE_COLORS — the `dye_color` attribute on a <team> element.
 *                          Armor-dye palette from pgm.dev/docs/reference/misc/colors.
 *
 * Helper functions:
 *   chatColorHex(name)   — resolve a PGM chat-color name → hex
 *   dyeColorHex(name)    — resolve a Minecraft dye-color name → hex
 *
 * Both helpers normalise underscore variants ("dark_purple" → "dark purple")
 * and fall back to a neutral slate-gray when the name is unknown.
 */

export const PGM_CHAT_COLORS = [
  { value: "black",        label: "Black",        hex: "#000000" },
  { value: "dark blue",    label: "Dark Blue",    hex: "#0000AA" },
  { value: "dark green",   label: "Dark Green",   hex: "#00AA00" },
  { value: "dark aqua",    label: "Dark Aqua",    hex: "#00AAAA" },
  { value: "dark red",     label: "Dark Red",     hex: "#AA0000" },
  { value: "dark purple",  label: "Dark Purple",  hex: "#AA00AA" },
  { value: "gold",         label: "Gold",         hex: "#FFAA00" },
  { value: "gray",         label: "Gray",         hex: "#AAAAAA" },
  { value: "dark gray",    label: "Dark Gray",    hex: "#555555" },
  { value: "blue",         label: "Blue",         hex: "#5555FF" },
  { value: "green",        label: "Green",        hex: "#55FF55" },
  { value: "aqua",         label: "Aqua",         hex: "#55FFFF" },
  { value: "red",          label: "Red",          hex: "#FF5555" },
  { value: "light purple", label: "Light Purple", hex: "#FF55FF" },
  { value: "yellow",       label: "Yellow",       hex: "#FFFF55" },
  { value: "white",        label: "White",        hex: "#FFFFFF" },
];

export const MINECRAFT_DYE_COLORS = [
  { value: "white",      label: "White",      hex: "#FFFFFF" },
  { value: "orange",     label: "Orange",     hex: "#D87F33" },
  { value: "magenta",    label: "Magenta",    hex: "#B24CD8" },
  { value: "light blue", label: "Light Blue", hex: "#6699D8" },
  { value: "yellow",     label: "Yellow",     hex: "#E5E533" },
  { value: "lime",       label: "Lime",       hex: "#7FCC19" },
  { value: "pink",       label: "Pink",       hex: "#F27FA5" },
  { value: "gray",       label: "Gray",       hex: "#4C4C4C" },
  { value: "silver",     label: "Silver",     hex: "#999999" },
  { value: "cyan",       label: "Cyan",       hex: "#4C7F99" },
  { value: "purple",     label: "Purple",     hex: "#7F3FB2" },
  { value: "blue",       label: "Blue",       hex: "#334CB2" },
  { value: "brown",      label: "Brown",      hex: "#664C33" },
  { value: "green",      label: "Green",      hex: "#667F33" },
  { value: "red",        label: "Red",        hex: "#993333" },
  { value: "black",      label: "Black",      hex: "#191919" },
];

/** Resolve a PGM chat-color name → hex, falling back to neutral gray. */
export function chatColorHex(colorName) {
  const normalised = (colorName ?? "").replace(/_/g, " ").toLowerCase();
  return PGM_CHAT_COLORS.find(c => c.value === normalised)?.hex ?? "#475569";
}

/** Resolve a Minecraft dye-color name → hex, falling back to neutral gray. */
export function dyeColorHex(colorName) {
  const normalised = (colorName ?? "").replace(/_/g, " ").toLowerCase();
  return MINECRAFT_DYE_COLORS.find(c => c.value === normalised)?.hex ?? "#475569";
}
