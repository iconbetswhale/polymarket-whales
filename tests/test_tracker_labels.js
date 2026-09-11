"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");

const source = fs.readFileSync(require.resolve("../static/app.js"), "utf8");
const teamHelpers = source.slice(
  source.indexOf("function trackerShortMatchup"),
  source.indexOf("function trackerSharpCompact"),
);
const labelHelpers = source.slice(
  source.indexOf("const TRACKER_COMPACT_PROP_STATS"),
  source.indexOf("function trackerMobileDetail"),
);
const context = {
  number(value) {
    if (value === null || value === undefined || value === "") return null;
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : null;
  },
};

vm.runInNewContext(`${teamHelpers}\n${labelHelpers}\nthis.compact = trackerCompactBetLabel;`, context);

const matchup = "New York Mets vs New York Yankees";
assert.equal(context.compact("New York Mets", "Moneyline", null, matchup), "NY Mets ML");
assert.equal(context.compact("Over 8.5 Runs", "Game Total", 8.5, matchup), "Mets/Yankees O8.5");
assert.equal(context.compact("New York Mets -1.5", "Spread", -1.5, matchup), "NY Mets -1.5");
assert.equal(
  context.compact("Buffalo Bills -6.5", "Spread", -6.5, "Buffalo Bills vs Miami Dolphins", "", "NFL"),
  "BUF Bills -6.5",
);
assert.equal(
  context.compact("Taylor Fritz", "Moneyline", null, "Taylor Fritz vs Ben Shelton", "", "Tennis"),
  "Taylor Fritz ML",
);
assert.equal(
  context.compact("Shohei Ohtani Over 1.5", "batter_total_bases Player Total Bases", 1.5, "Dodgers vs Giants"),
  "Shohei Ohtani O1.5 Total Bases",
);
assert.equal(
  context.compact("Max Fried Over 5.5", "pitcher_strikeouts Pitcher Strikeouts", 5.5, "Yankees vs Red Sox"),
  "Max Fried O5.5 Strikeouts",
);
assert.equal(context.compact("Over 4.5", "First Half Total", 4.5, matchup), "Mets/Yankees O4.5 1H");
assert.equal(context.compact("Over", "Game Total", 8.5, matchup), "Mets/Yankees O8.5");
assert.equal(
  context.compact("Patrick Mahomes Over 274.5", "player_passing_yards Player Passing Yards", 274.5, "Chiefs vs Raiders"),
  "Patrick Mahomes O274.5 Passing Yards",
);
assert.equal(context.compact("Under 6.5", "Match Total Games", 6.5, "Carlos Alcaraz vs Jannik Sinner"), "Alcaraz/Sinner U6.5");

console.log("tracker compact label tests passed");
