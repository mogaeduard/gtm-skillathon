# Run sheet

Fallback at ~60 seconds: open [`demo/output/prospect-fit.md`](demo/output/prospect-fit.md).

## Say this — 20 seconds

**Team:** publi22 (mogaeduard, hackatonnnnn)

**Track:** personalized-growth-engines

**Who has the problem:** the partnerships lead at VIP, a Romanian student organization that signs company partners. They qualified 135 companies by eye, on a spreadsheet, over two weeks.

**The job this skill does:** it derives the ideal customer profile from the companies that already said yes, by reading their public websites live, holds that up against the ICP you say you have and names your blind spots, then finds or scores prospects against it with a source URL behind every claim, and drafts an opener for the top three. Where you are wrong, who to call, what to say, in one run.

**Boundary — what it never does:** it never touches people, emails or profiles, it never sends anything, and it says "insufficient evidence" instead of guessing.

Say: "Every company writes an ICP in a slide. This one is computed from the customers you actually closed. We are running it on Apify, tonight's sponsor, because their customer list is public, so everything on this screen can be checked."

## Run this — 60 seconds

1. Codex is open at the repository root.
2. Paste [`demo/seed-prompt.md`](demo/seed-prompt.md).
3. **Codex will ask to run a command that needs the network. Click "Allow once".** If the script prints `NO NETWORK`, it is asking for that approval: run it again after approving.
4. Watch for: the ranked table printed in the terminal first, within roughly 20 seconds, then three files under `out/`. The drafts are written after the table, so the result is on screen before the drafting finishes.
5. If nothing visible after 60 seconds, open the fallback: [`demo/output/prospect-fit.md`](demo/output/prospect-fit.md).

While it runs, say: "It is fetching 22 company websites right now, twelve customers and ten prospects, homepage plus the careers or about page for each. The collector takes about four seconds. Everything after that is the model writing the three drafts."

## Show this — 25 seconds

Open `out/icp-gap.md` first, then `out/prospect-fit.md`.

Say: "This is the part nobody has. Left column is what Apify says about itself, taken from its own pages. Right column is what its customers actually are. Half of them are SaaS products and the positioning never says the word. Sixty percent are hiring right now, which is a timing signal nobody is using. And Apify sells to solo developers and to enterprise, while its customers cluster at two hundred to a thousand people: the middle is where it actually wins." Point to the fit column, then to the evidence column, then to the "Insufficient evidence" section at the bottom.

**Result:** the ICP is derived from 12 customer companies, 10 of which had usable public evidence, confidence `medium`. Three prospects score 80 or more: Omniconvert 84, UiPath 83, Axway 80. Four score under 30 and are marked unfit. `out/openers.md` holds one draft per top company, addressed to a role, never to a person.

Say: "Apify's real customer base is SaaS products and martech, hiring, English language sites, mostly React and Google Tag Manager. Omniconvert scores 84 because it matches on business line, hiring and language, and it loses points on stack overlap. Every one of those numbers has a URL and a timestamp beside it."

Say, pointing at the bottom of the table: "And look down here. Romanian Software scores one. It tells you why: payroll instead of software, not hiring, and a site only in Romanian while every customer we closed has an English site. EveryMatrix scores twenty seven, gaming, and nobody in our customer list is gaming. That is the useful part. It does not only tell you who to call. It tells you who to stop wasting time on, and why."

**Evidence:** every ranked row in `prospect-fit.md` carries the evidence URL and its `retrieved_at`. Prospects whose page could not be read are listed separately and never given a score.

**Fallback output was produced:** 2026-08-28 at 20:09 EEST, by running this exact seed prompt in Codex CLI 0.150.1 from a fresh `git clone` of the submitted commit, on a clean Codex profile holding nothing but the login. Measured end to end: 68 seconds, of which the collector took 4 and the ranked table appeared first. Five clean profile runs of this prompt tonight took 80, 115, 86, 68 and 74 seconds, median 80; all of the variation is model writing time, and the ranked table was on screen within the first 20 seconds in every one. The last one, at 20:18, reproduced every number in this run sheet.

## Evals — 10 seconds

| Case | Result | Where |
| --- | --- | --- |
| Intended | pass, 10 of 10 prospects ranked with sources, 3 above 80 | [`demo/evals.md`](demo/evals.md) |
| Insufficient evidence | pass, a dead domain and a JavaScript only page both refused a score; a 2 customer ICP is labelled insufficient | [`demo/evals.md`](demo/evals.md) |
| Failure / exclusion | pass, a file with an email column exits 2 before any network call | [`demo/evals.md`](demo/evals.md) |
| No prospect list | pass, a public sponsor page yields companies, scored with the page URL and time recorded | [`demo/evals.md`](demo/evals.md) |

## One more thing, if there is no list — 15 seconds

Open [`demo/output/discovery/prospect-fit.md`](demo/output/discovery/prospect-fit.md).

Say: "Same skill, no prospect list at all. We pointed it at the public sponsor page of DevTalks, a Romanian developer conference. It read the page, kept the company links, dropped the directories and the social networks, and scored what it found. That is the sourcing step: give it a sponsor page, a partner page, a portfolio page, and it produces the list, the scores and the drafts in the same run."

The source URL, the HTTP status and the retrieval time of that page are in `demo/output/discovery/discovery.json`. Discovery costs one extra HTTP request: this exact run took 91 seconds end to end on a clean Codex profile from a fresh clone of the submitted commit, 9 companies found, 6 ranked, 3 marked insufficient evidence, 3 openers drafted.

## Close — 5 seconds

**Reusable on:** any two CSVs with `company,domain` columns, a published Google Sheet URL, or no prospect list at all, in which case any public list page becomes the source. The same evening it ran unchanged on `demo/input/prospects-all.csv`, all 35 companies from the same source.

**Material limitation:** this reads public websites. Revenue, deal size, sales cycle and retention are printed only when the CRM columns exist in the input, otherwise the report says "not in input". No site in this run stated an employee count, so the size axis scored zero for everyone and the report says so.

## If a judge asks

- **How do you know our stated ICP is wrong?** We do not assert it. `out/icp-gap.md` puts your own words next to what your customers' sites show, axis by axis, and labels the rows. An overclaim is worded as a question to check, not a verdict, because a customer whose site does not say what it sells will not be counted in its real segment.
- **Why not ask ChatGPT what our ICP is?** It would answer from memory of the internet. This fetches your own customers' sites, counts what they have in common, and shows the count. Change one customer and the profile changes.
- **Is the fit score real or is the model inventing it?** The score is computed in `scripts/collect.py`, in Python, from the fetched pages. The model is told not to recompute or adjust it. Every component prints its own points and the reason.
- **Does it work with our CRM?** Point it at your export. `company,domain` are the only required columns; `status`, `deal_size`, `days_to_close`, `industry`, `employees`, `country`, `revenue`, `retention` are used if present and reported as "not in input" if not. It also accepts a published Google Sheet CSV URL instead of a file.
- **Where does personal data go?** Nowhere. If the input has an email, phone, LinkedIn or contact column, the collector exits with `REFUSED` before opening a single connection. Try it: `demo/input/evals/prospects-refused.csv`.
- **Where do prospects come from if we do not have a list?** `--discover-from <url>` reads one public list page, keeps the outbound company links and drops directories, social networks, press and job boards, using the same denylist we run in our own outbound work. It writes `out/discovered.csv` and records the page URL and retrieval time in `out/discovery.json`. Companies found this way are candidates, never described as customers of that page.
- **Where did the prospect list come from?** An Apify Google Maps run for software companies in Bucharest, run id `fRPr1bcCJo3E5YJOw`, 2026-08-28 15:48 UTC, cost 3.8 cents. The provenance is in `demo/input/SOURCES.md`.
