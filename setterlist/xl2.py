import csv, json
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment
from openpyxl.utils import get_column_letter

wb = Workbook(); wb.remove(wb.active)
HFILL = PatternFill("solid", fgColor="1F3864")

def add(path, title, widths, numcols=(0,)):
    rows = list(csv.reader(open(path)))
    ws = wb.create_sheet(title)
    ws.append(rows[0])
    for r in rows[1:]:
        ws.append([int(v) if (i in numcols and str(v).strip().lstrip("-").isdigit()) else v
                   for i, v in enumerate(r)])
    for c in ws[1]:
        c.font = Font(bold=True, color="FFFFFF"); c.fill = HFILL
        c.alignment = Alignment(vertical="center", wrap_text=True)
    ws.row_dimensions[1].height = 30; ws.freeze_panes = "A2"
    for n, w in enumerate(widths, 1): ws.column_dimensions[get_column_letter(n)].width = w
    ws.auto_filter.ref = f"A1:{get_column_letter(len(rows[0]))}{len(rows)}"
    for i in range(2, len(rows) + 1):
        ws.cell(row=i, column=5).alignment = Alignment(wrap_text=True, vertical="top")
    return len(rows) - 1

n_fresh = add("list-fresh.csv", "1 New leads", [6,24,16,30,64,7,10,18,16,22,14,12,22,40], (0,5,6))
n_show  = add("list-showup-all.csv", "2 Webinar + newsletter", [6,24,16,30,64,7,10,18,16,22,14,12,22,40], (0,5,6))
n_fin   = add("list-finish.csv", "3 Finish the 10-19 list", [6,16,24,16,30,64,7,22,12,22,40], (0,6))
n_main = 25

ws = wb.create_sheet("What week one showed", 0)
L = [("Juan's first week on the 10/19 list, and what it tells us", True),
 ("", False),
 ("He dialled 119 of the 250 and made 132 calls, on four days: 16 on Monday the 19th, 12 on Tuesday, 44 on Thursday and 60 on Friday. Nothing over the weekend or so far today. 17 people answered and had a real conversation, which is a 14% pickup rate.", False),
 ("Ten of those 17 conversations became appointments. That is a 59% booking rate on anyone who actually picks up, and it is the number worth protecting — the list converts once he gets someone on the phone. Two of the appointments have been kept, one was a no-show, one cancelled, and eight are still to come.", False),
 ("", False),
 ("Who picks up", True),
 ("How new the lead is, and almost nothing else. Leads under a month old answered 25% of the time; leads over six months old answered 7%. Priority A on my first sheet answered 10% while priority C answered 24%, so my original ranking was wrong on this: I weighted old-but-engaged people too highly, and they are the hardest to reach.", False),
 ("People who had replied to a text at some point answered less often (8%) than people who never had (22%), because most of those replies were months old. Only a reply in the last two weeks means anything.", False),
 ("The hour matters. Juan's pickup rate was 29% at 1pm and 22% at 2pm in the contact's own time zone, against 9% at 3pm and 11% at 4pm — and 71 of his 119 dials went out at 3pm or 4pm. Moving his calling window to noon-2pm local is the single cheapest change available.", False),
 ("", False),
 ("Who shows up once booked", True),
 ("This is measured across all 843 appointments in both accounts that have an outcome, not just Juan's, so it is solid. The base show rate is 33%.", False),
 ("Someone who attended a webinar live keeps 75% of their appointments. Watching the replay is worth nothing (29%, the same as never having seen one).", False),
 ("Weekly newsletter subscribers show 72% of the time. People who clicked a webinar invite show 60%. Anyone already carrying your tier 1 tag shows 59%, while tier 5 shows 18%.", False),
 ("Anyone who has missed an appointment before shows only 9% of the time. They are still worth calling, but the time needs confirming twice.", False),
 ("Noon appointments are kept 43% of the time against 24% at 2pm, and Tuesday is the best day at 37%.", False),
 ("People who gave a capital answer under $5k show 24% against 32% for $10k or more, so capital is a weak signal and not worth filtering on.", False),
 ("", False),
 ("The three lists in this workbook", True),
 (f"1 New leads — {n_fresh} people, everyone who has come in within 60 days and has not been dialled, newest first. This is the highest pickup rate available and it is small, because only about 240 new leads reach the SMS account in a month. {110} of them are tagged \"10/26 juan new leads\".", False),
 (f"2 Webinar + newsletter — {n_show} people who attended a webinar live or subscribe to the newsletter, with prior no-shows kept out. Lower pickup than the new leads, but the ones who do answer are the ones who turn up. All {n_show} are tagged \"10/26 juan webinar + newsletter\" in the SMS account. {n_main} of them had no SMS record at all and were copied in from the main account, tagged \"copied from main account\"; the other 225 were already there.", False),
 (f"3 Finish the 10/19 list — the {n_fin} people from last week he never dialled, still in rank order, with 63 of them priority A. Already tagged from last week.", False),
 ("Everyone on list 2 is now in the SMS sub-account and tagged, so there is nothing left in the main account to chase. Thirteen people who turned out to be on the 10/19 list or already dialled were taken back off the tag, so the three lists stay separate.", False),
 ("", False),
 ("Every list excludes the same things as before: anyone who owns the bot, the navigator or futures, anyone do-not-call or without a dialable number, anyone with an appointment already booked, and anyone disqualified. People Juan has already dialled or tagged for long-term nurture are kept out too, and nobody appears on two lists.", False),
 ("", False),
 ("If you only tell him two things", True),
 ("Call between noon and 2pm in the contact's time zone, not 3pm and 4pm.", False),
 ("Work the new-leads list the day the leads land, and use the webinar list to fill the rest of the day.", False)]
for text, bold in L:
    ws.append([text]); cell = ws.cell(row=ws.max_row, column=1)
    cell.font = Font(bold=bold, size=12 if bold else 11)
    cell.alignment = Alignment(wrap_text=True, vertical="top")
ws.column_dimensions["A"].width = 118
wb.save("/mnt/project-files/setter-lists/juan-call-lists-2026-10-26.xlsx")
print("saved", n_fresh, n_show, n_fin, n_main)
