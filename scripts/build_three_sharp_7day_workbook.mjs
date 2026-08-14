import fs from "node:fs/promises";
import path from "node:path";
import { SpreadsheetFile, Workbook } from "file:///C:/Users/15617/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/@oai/artifact-tool/dist/artifact_tool.mjs";

const sourcePath = process.argv[2] || "outputs/three-sharp-7day-recap-2026-08-04.json";
const outputDir = process.argv[3] || "outputs/019f682e-d751-7700-85f8-61e86956cf9d";
const data = JSON.parse(await fs.readFile(sourcePath, "utf8"));
const walletNames = Object.keys(data.wallets);

const wb = Workbook.create();
const summary = wb.worksheets.add("7-Day Summary");
const market = wb.worksheets.add("Market Breakdown");
const sharp = wb.worksheets.add("Sharp Breakdown");
const agreement = wb.worksheets.add("Agreement Analysis");
const ledger = wb.worksheets.add("Bet Ledger");
const signals = wb.worksheets.add("Sharp Signals");
const method = wb.worksheets.add("Methodology");

const C = {
  bg: "#071018", panel: "#0D1B27", panel2: "#112838", header: "#172F41",
  cyan: "#20B8F0", green: "#67E86B", red: "#FF6666", amber: "#F5C451",
  white: "#F4F8FB", muted: "#91A5B5", border: "#274357", purple: "#9277FF",
};

const teamNames = {
  ari:"Arizona Diamondbacks", atl:"Atlanta Braves", bal:"Baltimore Orioles", bos:"Boston Red Sox",
  chc:"Chicago Cubs", chw:"Chicago White Sox", cin:"Cincinnati Reds", cle:"Cleveland Guardians",
  col:"Colorado Rockies", det:"Detroit Tigers", hou:"Houston Astros", kc:"Kansas City Royals",
  laa:"Los Angeles Angels", lad:"Los Angeles Dodgers", mia:"Miami Marlins", mil:"Milwaukee Brewers",
  min:"Minnesota Twins", nym:"New York Mets", nyy:"New York Yankees", oak:"Oakland Athletics",
  phi:"Philadelphia Phillies", pit:"Pittsburgh Pirates", sd:"San Diego Padres", sea:"Seattle Mariners",
  sf:"San Francisco Giants", stl:"St. Louis Cardinals", tb:"Tampa Bay Rays", tex:"Texas Rangers",
  tor:"Toronto Blue Jays", wsh:"Washington Nationals", was:"Washington Nationals",
};

function eventLabel(slug) {
  const m = String(slug || "").match(/^mlb-([a-z]+)-([a-z]+)-\d{4}-\d{2}-\d{2}$/i);
  if (!m) return String(slug || "").replaceAll("-", " ");
  return `${teamNames[m[1].toLowerCase()] || m[1].toUpperCase()} vs ${teamNames[m[2].toLowerCase()] || m[2].toUpperCase()}`;
}

function a1Col(n) {
  let s = "";
  while (n > 0) { n--; s = String.fromCharCode(65 + (n % 26)) + s; n = Math.floor(n / 26); }
  return s;
}

function baseSheet(sheet, lastCol, lastRow) {
  sheet.showGridLines = false;
  sheet.getRange(`A1:${lastCol}${lastRow}`).format.fill = C.bg;
  sheet.getRange(`A1:${lastCol}${lastRow}`).format.font = { name: "Aptos", color: C.white, size: 10 };
}

function titleBand(sheet, range, title, subtitle) {
  sheet.getRange(range).merge();
  const start = range.split(":")[0];
  sheet.getRange(start).values = [[title]];
  sheet.getRange(start).format = {
    fill: C.header,
    font: { name: "Aptos Display", color: C.white, size: 20, bold: true },
    verticalAlignment: "center",
    borders: { preset: "outside", style: "thin", color: C.border },
  };
  const row = Number(start.match(/\d+/)[0]);
  const col1 = start.match(/[A-Z]+/)[0];
  const end = range.split(":")[1].match(/[A-Z]+/)[0];
  sheet.getRange(`${col1}${row + 1}:${end}${row + 1}`).merge();
  sheet.getRange(`${col1}${row + 1}`).values = [[subtitle]];
  sheet.getRange(`${col1}${row + 1}`).format = { fill: C.header, font: { color: C.muted, size: 10 }, verticalAlignment: "center" };
}

function sectionHeader(sheet, range, text) {
  sheet.getRange(range).merge();
  const start = range.split(":")[0];
  sheet.getRange(start).values = [[text]];
  sheet.getRange(start).format = {
    fill: C.panel2,
    font: { color: C.white, size: 12, bold: true },
    borders: { preset: "outside", style: "thin", color: C.border },
    verticalAlignment: "center",
  };
}

function styleHeader(range) {
  range.format = {
    fill: C.header,
    font: { color: C.white, bold: true, size: 10 },
    borders: { preset: "all", style: "thin", color: C.border },
    horizontalAlignment: "center",
    verticalAlignment: "center",
    wrapText: true,
  };
}

function styleTable(range) {
  range.format = {
    fill: C.panel,
    font: { color: C.white, size: 10 },
    borders: { preset: "all", style: "thin", color: C.border },
    verticalAlignment: "center",
  };
}

// ---------------- Bet Ledger (authoritative decision layer) ----------------
const decisionRows = data.decision_ledger.map((d) => [
  new Date(`${d.date}T12:00:00`), eventLabel(d.event_slug), d.market_title || d.market_slug,
  String(d.market_type || "").replace(/^./, x => x.toUpperCase()), d.decision, d.consensus_type,
  Array.isArray(d.supporters) ? d.supporters.join(", ") : "", d.outcome || d.sides || "",
  d.entry_price_proxy ?? null, null, d.stake_units ?? 0,
  d.decision === "VETO" ? "Veto" : (d.won ? "Won" : "Lost"), null, null,
  d.supporter_count ?? 0, `'${d.condition_id}`, d.event_slug, d.market_slug,
]);
const ledgerHeaders = ["Date","Event","Market","Type","Decision","Consensus","Sharps","Selection","Entry Probability","Entry American","Stake (u)","Result","Profit (u)","Bet ROI","Sharp Count","Condition ID","Event Slug","Market Slug"];
const ledgerLast = decisionRows.length + 1;
baseSheet(ledger, "R", Math.max(ledgerLast + 3, 40));
ledger.getRange(`A1:R1`).values = [ledgerHeaders]; styleHeader(ledger.getRange("A1:R1"));
ledger.getRange(`A2:R${ledgerLast}`).values = decisionRows; styleTable(ledger.getRange(`A2:R${ledgerLast}`));
ledger.getRange("J2").formulas = [["=IF(I2=\"\",\"\",IF(I2>=0.5,-ROUND(100*I2/(1-I2),0),ROUND(100*(1-I2)/I2,0)))"]];
ledger.getRange(`J2:J${ledgerLast}`).fillDown();
ledger.getRange("M2").formulas = [["=IF(E2<>\"BET\",0,IF(L2=\"Won\",K2*((1-I2)/I2),-K2))"]];
ledger.getRange(`M2:M${ledgerLast}`).fillDown();
ledger.getRange("N2").formulas = [["=IF(OR(E2<>\"BET\",K2=0),\"\",M2/K2)"]];
ledger.getRange(`N2:N${ledgerLast}`).fillDown();
ledger.getRange(`A2:A${ledgerLast}`).setNumberFormat("yyyy-mm-dd");
ledger.getRange(`I2:I${ledgerLast}`).setNumberFormat("0.0%");
ledger.getRange(`J2:J${ledgerLast}`).setNumberFormat("+0;-0;0");
ledger.getRange(`K2:K${ledgerLast}`).setNumberFormat("0.000\"u\"");
ledger.getRange(`M2:M${ledgerLast}`).setNumberFormat("+0.000\"u\";-0.000\"u\";0.000\"u\"");
ledger.getRange(`N2:N${ledgerLast}`).setNumberFormat("+0.00%;-0.00%;0.00%");
ledger.freezePanes.freezeRows(1);
ledger.freezePanes.freezeColumns(2);
ledger.getRange(`A1:R${ledgerLast}`).format.rowHeight = 22;
ledger.getRange("A:A").format.columnWidth = 12;
ledger.getRange("B:B").format.columnWidth = 31;
ledger.getRange("C:C").format.columnWidth = 25;
ledger.getRange("D:F").format.columnWidth = 15;
ledger.getRange("G:H").format.columnWidth = 24;
ledger.getRange("I:O").format.columnWidth = 14;
ledger.getRange("P:R").format.columnWidth = 24;
ledger.getRange(`L2:L${ledgerLast}`).conditionalFormats.add("containsText", { text: "Won", format: { fill: "#143E2A", font: { color: C.green, bold: true } } });
ledger.getRange(`L2:L${ledgerLast}`).conditionalFormats.add("containsText", { text: "Lost", format: { fill: "#462126", font: { color: C.red, bold: true } } });
ledger.getRange(`L2:L${ledgerLast}`).conditionalFormats.add("containsText", { text: "Veto", format: { fill: "#42361C", font: { color: C.amber, bold: true } } });
ledger.getRange(`M2:M${ledgerLast}`).conditionalFormats.add("cellIs", { operator: "greaterThan", formula: 0, format: { font: { color: C.green, bold: true } } });
ledger.getRange(`M2:M${ledgerLast}`).conditionalFormats.add("cellIs", { operator: "lessThan", formula: 0, format: { font: { color: C.red, bold: true } } });

// ---------------- Sharp Signals ----------------
const signalRows = data.wallet_signal_ledger.map((s) => [
  new Date(`${s.date}T12:00:00`), eventLabel(s.event_slug), String(s.market_type || "").replace(/^./, x => x.toUpperCase()),
  s.wallet, s.outcome, s.price, null, s.leader_risked_dollars, s.opposing_risked_dollars,
  s.net_risked_dollars, s.relative_units, s.status, s.won ? "Won" : "Lost", 1, null, `'${s.condition_id}`,
]);
const signalHeaders = ["Date","Event","Type","Sharp","Selection","Entry Probability","Entry American","Leader Risked","Opposing Risked","Net Risked","Relative Units","Status","Result","Std Stake (u)","Std Profit (u)","Condition ID"];
const signalLast = signalRows.length + 1;
baseSheet(signals, "P", Math.max(signalLast + 3, 45));
signals.getRange("A1:P1").values = [signalHeaders]; styleHeader(signals.getRange("A1:P1"));
signals.getRange(`A2:P${signalLast}`).values = signalRows; styleTable(signals.getRange(`A2:P${signalLast}`));
signals.getRange("G2").formulas = [["=IF(F2>=0.5,-ROUND(100*F2/(1-F2),0),ROUND(100*(1-F2)/F2,0))"]];
signals.getRange(`G2:G${signalLast}`).fillDown();
signals.getRange("O2").formulas = [["=IF(M2=\"Won\",N2*((1-F2)/F2),-N2)"]];
signals.getRange(`O2:O${signalLast}`).fillDown();
signals.getRange(`A2:A${signalLast}`).setNumberFormat("yyyy-mm-dd");
signals.getRange(`F2:F${signalLast}`).setNumberFormat("0.0%");
signals.getRange(`G2:G${signalLast}`).setNumberFormat("+0;-0;0");
signals.getRange(`H2:J${signalLast}`).setNumberFormat("$#,##0.00");
signals.getRange(`K2:K${signalLast}`).setNumberFormat("0.00x");
signals.getRange(`N2:O${signalLast}`).setNumberFormat("0.000\"u\"");
signals.freezePanes.freezeRows(1); signals.freezePanes.freezeColumns(2);
signals.getRange("A:A").format.columnWidth = 12; signals.getRange("B:B").format.columnWidth = 31;
signals.getRange("C:D").format.columnWidth = 17; signals.getRange("E:E").format.columnWidth = 25;
signals.getRange("F:O").format.columnWidth = 15; signals.getRange("P:P").format.columnWidth = 24;
signals.getRange(`M2:M${signalLast}`).conditionalFormats.add("containsText", { text: "Won", format: { font: { color: C.green, bold: true } } });
signals.getRange(`M2:M${signalLast}`).conditionalFormats.add("containsText", { text: "Lost", format: { font: { color: C.red, bold: true } } });
signals.getRange(`O2:O${signalLast}`).conditionalFormats.add("cellIs", { operator: "greaterThan", formula: 0, format: { font: { color: C.green, bold: true } } });
signals.getRange(`O2:O${signalLast}`).conditionalFormats.add("cellIs", { operator: "lessThan", formula: 0, format: { font: { color: C.red, bold: true } } });

// ---------------- Summary ----------------
baseSheet(summary, "L", 45);
titleBand(summary, "A1:L1", "Three-Sharp Model — 7-Day Recap", `${data.period.start} through ${data.period.end} · Actual settled MLB main-market signals · Formula-backed audit`);
summary.getRange("A1:L1").format.rowHeight = 34; summary.getRange("A2:L2").format.rowHeight = 22;
const cards = [
  ["A4:C4","Bets",`=COUNTIF('Bet Ledger'!$E$2:$E$${ledgerLast},\"BET\")`],
  ["D4:F4","Record",`=COUNTIFS('Bet Ledger'!$E$2:$E$${ledgerLast},\"BET\",'Bet Ledger'!$L$2:$L$${ledgerLast},\"Won\")&\"-\"&COUNTIFS('Bet Ledger'!$E$2:$E$${ledgerLast},\"BET\",'Bet Ledger'!$L$2:$L$${ledgerLast},\"Lost\")`],
  ["G4:I4","Hit Rate",`=COUNTIFS('Bet Ledger'!$E$2:$E$${ledgerLast},\"BET\",'Bet Ledger'!$L$2:$L$${ledgerLast},\"Won\")/COUNTIF('Bet Ledger'!$E$2:$E$${ledgerLast},\"BET\")`],
  ["J4:L4","Profit",`=SUMIF('Bet Ledger'!$E$2:$E$${ledgerLast},\"BET\",'Bet Ledger'!$M$2:$M$${ledgerLast})`],
  ["A7:C7","ROI",`=SUMIF('Bet Ledger'!$E$2:$E$${ledgerLast},\"BET\",'Bet Ledger'!$M$2:$M$${ledgerLast})/SUMIF('Bet Ledger'!$E$2:$E$${ledgerLast},\"BET\",'Bet Ledger'!$K$2:$K$${ledgerLast})`],
  ["D7:F7","Staked",`=SUMIF('Bet Ledger'!$E$2:$E$${ledgerLast},\"BET\",'Bet Ledger'!$K$2:$K$${ledgerLast})`],
  ["G7:I7","Agreed Plays",`=COUNTIFS('Bet Ledger'!$E$2:$E$${ledgerLast},\"BET\",'Bet Ledger'!$O$2:$O$${ledgerLast},\">=2\")`],
  ["J7:L7","Disagreement Vetoes",`=COUNTIF('Bet Ledger'!$E$2:$E$${ledgerLast},\"VETO\")`],
];
for (const [rg,label,formula] of cards) {
  const [s,e] = rg.split(":"); const row = Number(s.match(/\d+/)[0]); const sc=s.match(/[A-Z]+/)[0]; const ec=e.match(/[A-Z]+/)[0];
  summary.getRange(rg).merge(); summary.getRange(s).values=[[label]];
  summary.getRange(`${sc}${row+1}:${ec}${row+2}`).merge(); summary.getRange(`${sc}${row+1}`).formulas=[[formula]];
  summary.getRange(`${sc}${row}:${ec}${row+2}`).format = { fill:C.panel, borders:{preset:"outside",style:"thin",color:C.border}, verticalAlignment:"center" };
  summary.getRange(s).format.font={color:C.muted,size:10,bold:true};
  summary.getRange(`${sc}${row+1}`).format.font={color:(label==="Profit"||label==="ROI")?C.green:C.white,size:20,bold:true};
}
summary.getRange("G5").setNumberFormat("0.00%"); summary.getRange("J5").setNumberFormat("+0.000\"u\";-0.000\"u\"");
summary.getRange("A8").setNumberFormat("0.00%"); summary.getRange("D8").setNumberFormat("0.000\"u\"");
sectionHeader(summary,"A11:F11","Daily Performance");
summary.getRange("A12:G12").values=[["Date","Bets","Wins","Losses","Hit Rate","Profit (u)","Cumulative (u)"]]; styleHeader(summary.getRange("A12:G12"));
const dates = Object.keys(data.daily).sort();
summary.getRange(`A13:A${12+dates.length}`).values=dates.map(d=>[new Date(`${d}T12:00:00`)]); summary.getRange(`A13:A${12+dates.length}`).setNumberFormat("mmm d");
for (let i=0;i<dates.length;i++) {
  const r=13+i;
  summary.getRange(`B${r}`).formulas=[[`=COUNTIFS('Bet Ledger'!$A$2:$A$${ledgerLast},A${r},'Bet Ledger'!$E$2:$E$${ledgerLast},\"BET\")`]];
  summary.getRange(`C${r}`).formulas=[[`=COUNTIFS('Bet Ledger'!$A$2:$A$${ledgerLast},A${r},'Bet Ledger'!$L$2:$L$${ledgerLast},\"Won\")`]];
  summary.getRange(`D${r}`).formulas=[[`=COUNTIFS('Bet Ledger'!$A$2:$A$${ledgerLast},A${r},'Bet Ledger'!$L$2:$L$${ledgerLast},\"Lost\")`]];
  summary.getRange(`E${r}`).formulas=[[`=IF(B${r}=0,\"\",C${r}/B${r})`]];
  summary.getRange(`F${r}`).formulas=[[`=SUMIFS('Bet Ledger'!$M$2:$M$${ledgerLast},'Bet Ledger'!$A$2:$A$${ledgerLast},A${r},'Bet Ledger'!$E$2:$E$${ledgerLast},\"BET\")`]];
  summary.getRange(`G${r}`).formulas=[[i===0?`=F${r}`:`=G${r-1}+F${r}`]];
}
styleTable(summary.getRange(`A13:G${12+dates.length}`));
summary.getRange(`E13:E${12+dates.length}`).setNumberFormat("0.0%");
summary.getRange(`F13:G${12+dates.length}`).setNumberFormat("+0.000\"u\";-0.000\"u\";0.000\"u\"");
summary.getRange(`F13:G${12+dates.length}`).conditionalFormats.add("cellIs", {operator:"greaterThan",formula:0,format:{font:{color:C.green,bold:true}}});
summary.getRange(`F13:G${12+dates.length}`).conditionalFormats.add("cellIs", {operator:"lessThan",formula:0,format:{font:{color:C.red,bold:true}}});
summary.getRange("H12:I12").values=[["Date","Cumulative Unit Profit"]];
for (let i=0;i<dates.length;i++) {
  const r=13+i;
  const label = new Date(`${dates[i]}T12:00:00`).toLocaleDateString("en-US", { month:"short", day:"numeric" });
  summary.getRange(`H${r}`).values=[[label]];
  summary.getRange(`I${r}`).formulas=[[`=G${r}`]];
}
summary.getRange(`H12:I${12+dates.length}`).format.font={color:C.bg,size:1};
const chart = summary.charts.add("line", summary.getRange(`H12:I${12+dates.length}`));
chart.setPosition("I11","L21"); chart.title="Cumulative Unit Profit"; chart.hasLegend=false;
chart.titleTextStyle.fontSize=12; chart.xAxis={axisType:"textAxis",textStyle:{fontSize:9}}; chart.yAxis={numberFormatCode:"0.0\"u\""};
sectionHeader(summary,"A23:L23","What happened in the sample");
summary.getRange("A24:L27").merge();
summary.getRange("A24").values=[["The model placed 28 qualifying bets and vetoed 3 cross-wallet disagreements. Two plays had 2+ sharps aligned; the other 26 were single-sharp qualifiers. Moneylines produced all positive unit profit in this seven-day window; the lone spread lost, and no qualifying totals were present."]];
summary.getRange("A24:L27").format={fill:C.panel,font:{color:C.white,size:11},borders:{preset:"outside",style:"thin",color:C.border},wrapText:true,verticalAlignment:"center"};
summary.getRange("A1:L30").format.columnWidth=13; summary.getRange("A:A").format.columnWidth=15;
summary.freezePanes.freezeRows(2);

// ---------------- Market Breakdown ----------------
baseSheet(market,"H",20); titleBand(market,"A1:H1","Performance by Market","Moneyline, spread and total results calculated from the Bet Ledger");
market.getRange("A4:H4").values=[["Market","Bets","Wins","Losses","Record","Hit Rate","Profit (u)","ROI"]]; styleHeader(market.getRange("A4:H4"));
market.getRange("A5:A7").values=[["Moneyline"],["Spread"],["Total"]];
for(let r=5;r<=7;r++){
  market.getRange(`B${r}`).formulas=[[`=COUNTIFS('Bet Ledger'!$D$2:$D$${ledgerLast},A${r},'Bet Ledger'!$E$2:$E$${ledgerLast},\"BET\")`]];
  market.getRange(`C${r}`).formulas=[[`=COUNTIFS('Bet Ledger'!$D$2:$D$${ledgerLast},A${r},'Bet Ledger'!$L$2:$L$${ledgerLast},\"Won\")`]];
  market.getRange(`D${r}`).formulas=[[`=COUNTIFS('Bet Ledger'!$D$2:$D$${ledgerLast},A${r},'Bet Ledger'!$L$2:$L$${ledgerLast},\"Lost\")`]];
  market.getRange(`E${r}`).formulas=[[`=C${r}&\"-\"&D${r}`]];
  market.getRange(`F${r}`).formulas=[[`=IF(B${r}=0,\"\",C${r}/B${r})`]];
  market.getRange(`G${r}`).formulas=[[`=SUMIFS('Bet Ledger'!$M$2:$M$${ledgerLast},'Bet Ledger'!$D$2:$D$${ledgerLast},A${r},'Bet Ledger'!$E$2:$E$${ledgerLast},\"BET\")`]];
  market.getRange(`H${r}`).formulas=[[`=IFERROR(G${r}/SUMIFS('Bet Ledger'!$K$2:$K$${ledgerLast},'Bet Ledger'!$D$2:$D$${ledgerLast},A${r},'Bet Ledger'!$E$2:$E$${ledgerLast},\"BET\"),\"\")`]];
}
styleTable(market.getRange("A5:H7")); market.getRange("F5:F7").setNumberFormat("0.00%"); market.getRange("G5:G7").setNumberFormat("+0.000\"u\";-0.000\"u\""); market.getRange("H5:H7").setNumberFormat("+0.00%;-0.00%");
market.getRange("A:H").format.columnWidth=18;

// ---------------- Sharp Breakdown ----------------
baseSheet(sharp,"J",20); titleBand(sharp,"A1:J1","Performance by Sharp","Each qualifying wallet signal standardized to a 1.0-unit stake; this is separate from combined-model sizing");
sharp.getRange("A4:J4").values=[["Sharp","Signals","Wins","Losses","Record","Hit Rate","Profit (u)","ROI","Agreements Supported","Disagreements Involved"]]; styleHeader(sharp.getRange("A4:J4"));
sharp.getRange("A5:A7").values=walletNames.map(w=>[w]);
for(let r=5;r<=7;r++){
  sharp.getRange(`B${r}`).formulas=[[`=COUNTIF('Sharp Signals'!$D$2:$D$${signalLast},A${r})`]];
  sharp.getRange(`C${r}`).formulas=[[`=COUNTIFS('Sharp Signals'!$D$2:$D$${signalLast},A${r},'Sharp Signals'!$M$2:$M$${signalLast},\"Won\")`]];
  sharp.getRange(`D${r}`).formulas=[[`=COUNTIFS('Sharp Signals'!$D$2:$D$${signalLast},A${r},'Sharp Signals'!$M$2:$M$${signalLast},\"Lost\")`]];
  sharp.getRange(`E${r}`).formulas=[[`=C${r}&\"-\"&D${r}`]];
  sharp.getRange(`F${r}`).formulas=[[`=IF(B${r}=0,\"\",C${r}/B${r})`]];
  sharp.getRange(`G${r}`).formulas=[[`=SUMIF('Sharp Signals'!$D$2:$D$${signalLast},A${r},'Sharp Signals'!$O$2:$O$${signalLast})`]];
  sharp.getRange(`H${r}`).formulas=[[`=IF(B${r}=0,\"\",G${r}/B${r})`]];
  const w=walletNames[r-5]; const bw=data.by_wallet[w];
  sharp.getRange(`I${r}:J${r}`).values=[[bw.agreements_supported,bw.disagreements_involved]];
}
styleTable(sharp.getRange("A5:J7")); sharp.getRange("F5:F7").setNumberFormat("0.00%"); sharp.getRange("G5:G7").setNumberFormat("+0.000\"u\";-0.000\"u\""); sharp.getRange("H5:H7").setNumberFormat("+0.00%;-0.00%"); sharp.getRange("A:J").format.columnWidth=19;

// ---------------- Agreement Analysis ----------------
baseSheet(agreement,"H",25); titleBand(agreement,"A1:H1","Agreement & Disagreement Analysis","How often the three tracked sharps aligned, stood alone, or opposed one another");
agreement.getRange("A4:H4").values=[["Bucket","Decisions","Placed","Vetoed","Wins","Losses","Profit (u)","ROI"]]; styleHeader(agreement.getRange("A4:H4"));
agreement.getRange("A5:A7").values=[["Single sharp"],["Agreement (2+ sharps)"],["Disagreement"]];
agreement.getRange("B5").formulas=[[`=COUNTIF('Bet Ledger'!$F$2:$F$${ledgerLast},\"Single sharp\")`]];
agreement.getRange("B6").formulas=[[`=COUNTIFS('Bet Ledger'!$O$2:$O$${ledgerLast},\">=2\",'Bet Ledger'!$E$2:$E$${ledgerLast},\"BET\")`]];
agreement.getRange("B7").formulas=[[`=COUNTIF('Bet Ledger'!$E$2:$E$${ledgerLast},\"VETO\")`]];
agreement.getRange("C5").formulas=[["=B5"]]; agreement.getRange("C6").formulas=[["=B6"]]; agreement.getRange("C7").values=[[0]];
agreement.getRange("D5:D6").values=[[0],[0]]; agreement.getRange("D7").formulas=[["=B7"]];
agreement.getRange("E5").formulas=[[`=COUNTIFS('Bet Ledger'!$F$2:$F$${ledgerLast},\"Single sharp\",'Bet Ledger'!$L$2:$L$${ledgerLast},\"Won\")`]];
agreement.getRange("E6").formulas=[[`=COUNTIFS('Bet Ledger'!$O$2:$O$${ledgerLast},\">=2\",'Bet Ledger'!$L$2:$L$${ledgerLast},\"Won\")`]]; agreement.getRange("E7").values=[[0]];
agreement.getRange("F5").formulas=[[`=COUNTIFS('Bet Ledger'!$F$2:$F$${ledgerLast},\"Single sharp\",'Bet Ledger'!$L$2:$L$${ledgerLast},\"Lost\")`]];
agreement.getRange("F6").formulas=[[`=COUNTIFS('Bet Ledger'!$O$2:$O$${ledgerLast},\">=2\",'Bet Ledger'!$L$2:$L$${ledgerLast},\"Lost\")`]]; agreement.getRange("F7").values=[[0]];
agreement.getRange("G5").formulas=[[`=SUMIFS('Bet Ledger'!$M$2:$M$${ledgerLast},'Bet Ledger'!$F$2:$F$${ledgerLast},\"Single sharp\")`]];
agreement.getRange("G6").formulas=[[`=SUMIFS('Bet Ledger'!$M$2:$M$${ledgerLast},'Bet Ledger'!$O$2:$O$${ledgerLast},\">=2\",'Bet Ledger'!$E$2:$E$${ledgerLast},\"BET\")`]]; agreement.getRange("G7").values=[[0]];
agreement.getRange("H5").formulas=[[`=G5/SUMIFS('Bet Ledger'!$K$2:$K$${ledgerLast},'Bet Ledger'!$F$2:$F$${ledgerLast},\"Single sharp\")`]];
agreement.getRange("H6").formulas=[[`=G6/SUMIFS('Bet Ledger'!$K$2:$K$${ledgerLast},'Bet Ledger'!$O$2:$O$${ledgerLast},\">=2\",'Bet Ledger'!$E$2:$E$${ledgerLast},\"BET\")`]]; agreement.getRange("H7").values=[[null]];
styleTable(agreement.getRange("A5:H7")); agreement.getRange("G5:G7").setNumberFormat("+0.000\"u\";-0.000\"u\""); agreement.getRange("H5:H7").setNumberFormat("+0.00%;-0.00%"); agreement.getRange("A:H").format.columnWidth=20;
sectionHeader(agreement,"A10:H10","Definitions");
agreement.getRange("A11:H15").merge(); agreement.getRange("A11").values=[["Single sharp: one qualifying wallet backed the side. Agreement: at least two qualifying wallets backed the same side. Disagreement: qualifying wallets backed opposing sides in the same market; those decisions were vetoed and no model bet was placed. A moneyline and a run line are separate markets, so they are not classified as direct opposition here."]];
agreement.getRange("A11:H15").format={fill:C.panel,font:{color:C.white,size:11},borders:{preset:"outside",style:"thin",color:C.border},wrapText:true,verticalAlignment:"center"};

// ---------------- Methodology ----------------
baseSheet(method,"H",38); titleBand(method,"A1:H1","Methodology & Audit Notes","Definitions, scope, formulas and limitations for the seven-day recap");
const notes = [
  ["Reporting window", `${data.period.start} through ${data.period.end}, inclusive (America/New_York reporting dates).`],
  ["Wallets", walletNames.join(", ")],
  ["Included markets", "Settled MLB full-game moneylines, main ±1.5 run lines, and the highest-volume full-game total when present."],
  ["Placed-bet rule", "A qualifying directional wallet signal becomes a model bet unless another tracked sharp qualifies on the opposing side of the same market."],
  ["Agreement", "Two or more tracked sharps qualifying on the same side of the same market."],
  ["Disagreement", "Tracked sharps qualifying on opposing sides of the same market; the model vetoes the bet."],
  ["Model sizing", "Current THREE_SHARP_QK_CONVICTION_2X_V3 wallet-relative conviction sizing, expressed in units."],
  ["Entry price", "Copy-weighted median sharp entry-price proxy reconstructed from public Polymarket activity. This is not a timestamp-perfect executable NoVIG/ProphetX quote."],
  ["Profit formula", "Win: stake × ((1 − entry probability) ÷ entry probability). Loss: −stake."],
  ["ROI formula", "Total unit profit ÷ total units staked."],
  ["Sharp Breakdown", "Each qualifying wallet signal is standardized to 1.0 unit so the three wallets can be compared independently of combined-model sizing."],
  ["Data provenance", "Public Polymarket closed-position and activity records refreshed on 2026-08-04; exact condition IDs and source slugs are retained in the audit tabs."],
  ["Interpretation", "This is a short, realized seven-day recap—not a simulation and not proof that the observed ROI will persist."],
];
method.getRange("A4:B4").values=[["Item","Definition"]]; styleHeader(method.getRange("A4:B4"));
method.getRange(`A5:B${4+notes.length}`).values=notes; styleTable(method.getRange(`A5:B${4+notes.length}`));
method.getRange(`A5:A${4+notes.length}`).format.font={color:C.cyan,bold:true}; method.getRange(`B5:B${4+notes.length}`).format.wrapText=true;
method.getRange("A:A").format.columnWidth=24; method.getRange("B:B").format.columnWidth=95; method.getRange(`A5:B${4+notes.length}`).format.rowHeight=36;

// General polish.
for (const ws of [summary,market,sharp,agreement,ledger,signals,method]) {
  ws.getUsedRange().format.font.name = "Aptos";
}

await fs.mkdir(outputDir, { recursive: true });
const outputPath = path.join(outputDir, "three-sharp-7-day-recap-2026-08-04.xlsx");
const xlsx = await SpreadsheetFile.exportXlsx(wb);
await xlsx.save(outputPath);

const checks = await wb.inspect({ kind:"formula", sheetId:"7-Day Summary", range:"A1:L30", maxChars:12000, options:{maxResults:120} });
await fs.writeFile(path.join(outputDir,"formula-inspection.ndjson"), checks.ndjson || String(checks), "utf8");
for (const sheetName of ["7-Day Summary","Market Breakdown","Sharp Breakdown","Agreement Analysis","Bet Ledger","Sharp Signals","Methodology"]) {
  const preview = await wb.render({ sheetName, autoCrop:"all", scale:1, format:"png" });
  await fs.writeFile(path.join(outputDir, `${sheetName.toLowerCase().replaceAll(/[^a-z0-9]+/g,"-")}.png`), new Uint8Array(await preview.arrayBuffer()));
}
console.log(JSON.stringify({ outputPath, sheets:7, decisions:decisionRows.length, signals:signalRows.length }, null, 2));
