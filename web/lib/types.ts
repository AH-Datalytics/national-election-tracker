/* ------------------------------------------------------------------ */
/*  TypeScript interfaces matching the National Election Tracker API  */
/* ------------------------------------------------------------------ */

export interface State {
  code: string;
  name: string;
  fips: string;
  county_label: string;
  election_count: number;
  race_count: number;
  earliest_date: string | null;
  latest_date: string | null;
}

export interface County {
  code: string;
  name: string;
  fips: string;
  slug: string;
}

export interface Election {
  election_key: string;
  state: string;
  date: string;
  type: string;
  is_official: boolean;
  race_count: number;
}

export interface Choice {
  choice_key: string;
  choice_type: "candidate" | "ballot_option";
  name: string;
  party: string | null;
  ballot_order: number;
  outcome: string | null;
  vote_total: number;
  vote_percent: number;
}

export interface Race {
  race_key: string;
  election_key: string;
  office_category: string;
  office_name: string;
  district: string | null;
  is_ballot_measure: boolean;
  is_partisan: boolean;
  is_unexpired_term: boolean;
  total_votes: number;
  precincts_reporting: number | null;
  precincts_total: number | null;
  choices: Choice[];
}

export interface CountyChoiceResult {
  choice_key: string;
  votes: number;
  percent: number;
}

export interface CountyResult {
  county_code: string;
  county_name: string;
  precincts_reporting: number | null;
  precincts_total: number | null;
  choices: CountyChoiceResult[];
}

export interface LiveStatus {
  state: string;
  active: boolean;
  election_key?: string;
  election_date?: string;
  last_updated?: string;
}

export interface HealthResponse {
  status: string;
  database: string;
  states: number;
  elections: number;
}
