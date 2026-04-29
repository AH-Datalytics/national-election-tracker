/* ------------------------------------------------------------------ */
/*  Constants for the National Election Tracker                        */
/* ------------------------------------------------------------------ */

/** Party → hex color mapping. Covers common party name variations. */
export const PARTY_COLORS: Record<string, string> = {
  Republican: "#E81B23",
  Democrat: "#0015BC",
  Democratic: "#0015BC",
  Libertarian: "#FED105",
  Green: "#17AA5C",
  Independent: "#808080",
  Nonpartisan: "#666666",
  "No Party": "#666666",
  // Abbreviations (some state data uses these)
  REP: "#E81B23",
  DEM: "#0015BC",
  LBT: "#FED105",
  GRN: "#17AA5C",
  IND: "#808080",
  NP: "#666666",
};

/** Office categories, in display order. */
export const OFFICE_CATEGORIES = [
  "Federal",
  "State",
  "Judicial",
  "County",
  "Local",
  "School Board",
  "Ballot Measure",
] as const;

/** States that currently have data in the tracker. */
export const STATES_WITH_DATA: string[] = ["LA", "IN", "OH"];

/** Full US state names keyed by 2-letter code. */
export const STATE_NAMES: Record<string, string> = {
  AL: "Alabama",
  AK: "Alaska",
  AZ: "Arizona",
  AR: "Arkansas",
  CA: "California",
  CO: "Colorado",
  CT: "Connecticut",
  DE: "Delaware",
  FL: "Florida",
  GA: "Georgia",
  HI: "Hawaii",
  ID: "Idaho",
  IL: "Illinois",
  IN: "Indiana",
  IA: "Iowa",
  KS: "Kansas",
  KY: "Kentucky",
  LA: "Louisiana",
  ME: "Maine",
  MD: "Maryland",
  MA: "Massachusetts",
  MI: "Michigan",
  MN: "Minnesota",
  MS: "Mississippi",
  MO: "Missouri",
  MT: "Montana",
  NE: "Nebraska",
  NV: "Nevada",
  NH: "New Hampshire",
  NJ: "New Jersey",
  NM: "New Mexico",
  NY: "New York",
  NC: "North Carolina",
  ND: "North Dakota",
  OH: "Ohio",
  OK: "Oklahoma",
  OR: "Oregon",
  PA: "Pennsylvania",
  RI: "Rhode Island",
  SC: "South Carolina",
  SD: "South Dakota",
  TN: "Tennessee",
  TX: "Texas",
  UT: "Utah",
  VT: "Vermont",
  VA: "Virginia",
  WA: "Washington",
  WV: "West Virginia",
  WI: "Wisconsin",
  WY: "Wyoming",
  DC: "District of Columbia",
};

/** Primary navy color used across the site. */
export const COLOR_PRIMARY = "#1e3a5f";

/** Ballot measure choice colors. */
export const BALLOT_MEASURE_COLORS: Record<string, string> = {
  Yes: "#17AA5C",
  For: "#17AA5C",
  Approved: "#17AA5C",
  No: "#E81B23",
  Against: "#E81B23",
  Rejected: "#E81B23",
};
