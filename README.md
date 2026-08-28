# ICP Validator

**Your ICP is a slide. This computes the real one from the customers you actually closed, then tells you who to call and what to say.**

Every company has an ideal customer profile written down somewhere. Almost nobody has checked it against the customers they actually won. `$icp-validator` reads your closed customers' public websites, derives the profile they really share, holds it up against the one you say you have, and names the gap. Then it finds prospects that match it, scores each one with a source URL behind every point, and drafts the first touch.

- **Team:** publi22 (`mogaeduard`, `hackatonnnnn`) · **Track:** `personalized-growth-engines`
- **Run it:** open this repo in Codex and paste [`demo/seed-prompt.md`](demo/seed-prompt.md). Python 3 is the only runtime. No keys, no MCP, no install.
- **Verified:** 68 seconds end to end, from a fresh `git clone` on a clean Codex profile.

## What it actually found

Real committed output from [`demo/output/`](demo/output/), run against Apify, whose customer list is public so every number here can be checked.

**1. The ICP you say you have, against the one you have** — [`icp-gap.md`](demo/output/icp-gap.md)

| Axis | You say | Your customers show | Verdict |
| --- | --- | --- | --- |
| SaaS product | not named | 50% of customers | **blind spot** |
| Hiring right now | not named | 60% of customers | **blind spot** |
| Company size | enterprise, solo, startup | modal band 201-1000 | **mismatch** |
| Martech | named (lead generation) | 40% of customers | match |

> *60% of your customers are actively hiring. That is a timing signal you are not using anywhere in your messaging.*
>
> *You position at the two ends (enterprise, small team, solo) but your customers cluster at 201-1000. The middle is where you actually win.*

**2. Every prospect scored, with the arithmetic shown** — [`prospect-fit.md`](demo/output/prospect-fit.md)

| Rank | Company | Fit | Why | Evidence |
| ---: | --- | ---: | --- | --- |
| 1 | Omniconvert | **84** | category 40/40 martech · hiring 15/15 (69 job keyword hits) · tech 4/10 (jaccard 0.42) · size 0/10 | [omniconvert.com](https://www.omniconvert.com/) 17:08:06Z |
| 2 | UiPath | **83** | category 40/40 saas · hiring 15/15 · language 10/10 | [uipath.com](https://www.uipath.com/) 17:08:06Z |
| 10 | Romanian Software | **1** | category 0/40 hr_payroll not in the mix · not hiring · site is Romanian only | [sdworx.ro](https://www.sdworx.ro/ro-ro) 17:08:06Z |

**3. The first touch, quoting their own words** — [`openers.md`](demo/output/openers.md)

> Subject: **Omniconvert x Apify**
> *"Built for every layer of ecommerce growth ."* Source: https://www.omniconvert.com/ (retrieved 2026-08-28T17:08:06Z)
> That focus on ecommerce growth prompted this note. …

Every draft is marked `DRAFT`, addressed to a role and never a person, and nothing is ever sent.

## The part most tools skip

**It refuses.** Point it at a file with an `email`, `phone`, `linkedin` or `contact` column and it exits before opening a single socket:

```
$ python3 .agents/skills/icp-validator/scripts/collect.py --prospects demo/input/evals/prospects-refused.csv ...
REFUSED: personal data column/value detected (email)   # exit 2, no network, no report
```

**It says "I don't know."** Three of the nine companies in the discovery run returned a page it could not read. They are listed, with the reason, and given no score — instead of a confident number over nothing.

**The score is Python, not vibes.** `collect.py` computes fit from the fetched pages; the model is forbidden from recomputing or adjusting it. Every component prints its own points and its reason, so you can argue with the arithmetic instead of with a black box.

## You don't even need a prospect list

```bash
--discover-from https://www.devtalks.ro/     # a conference sponsor page
```

It reads one public list page — sponsors, partners, a VC portfolio, a directory — keeps the outbound company links, drops directories, social networks, press and job boards, and scores what it finds. Source URL and retrieval time land in `out/discovery.json`. Output committed in [`demo/output/discovery/`](demo/output/discovery/): 9 companies found, 6 ranked, 3 refused, 3 drafts, 91 seconds.

## Run it on your own company

```bash
# your customers and prospects: any CSV with company,domain — a file or a published Sheet URL
python3 .agents/skills/icp-validator/scripts/collect.py \
  --customers your-customers.csv \
  --prospects your-prospects.csv \
  --declared your-positioning.md \
  --out out
```

`status`, `deal_size`, `days_to_close`, `industry`, `employees`, `country`, `revenue` and `retention` are used when your export has them and printed as **`not in input`** when it does not. It never estimates a CRM number it was not given.

Check the logic without touching the network: `python3 .agents/skills/icp-validator/scripts/collect.py --selftest`

## What it does not do

- It reads **public company websites**. Not people, not emails, not LinkedIn profiles, not private data.
- Revenue, deal size, sales cycle and retention come from your CRM columns or not at all.
- The size axis scored **0/10 for everyone** in the demo run: no site in it states a headcount. That is in the report, not hidden.
- The declared-versus-actual comparison is keyword matching, deliberately blunt so every row is checkable against the file in front of you. Two Apify rows read as overclaims where the customers plausibly *are* that segment but their homepages do not say so — the report words those as a question to check, not a verdict.
- It stops at drafts. It never sends, never edits a CRM, never contacts anyone.

## Under the hood

One stdlib-only Python collector does every network call in parallel with timeouts and size caps, then writes the reports itself. The model reads a 3 KB summary and writes the drafts. That split is why the run fits in a demo slot: the collector takes 4 seconds for 22 companies and 42 pages, and everything after it is writing.

| | |
| --- | --- |
| Entry skill | [`.agents/skills/icp-validator/SKILL.md`](.agents/skills/icp-validator/SKILL.md) |
| Collector | [`scripts/collect.py`](.agents/skills/icp-validator/scripts/collect.py), stdlib only, Python 3.9+ |
| Run sheet | [`DEMO.md`](DEMO.md) |
| Evaluations | [`demo/evals.md`](demo/evals.md) — four cases, expectations written before the runs |
| Data provenance | [`demo/input/SOURCES.md`](demo/input/SOURCES.md) — Apify run id, actor build, dataset, cost |

Prospect and customer lists were built with [Apify](https://apify.com) at build time (Google Maps actor, run `fRPr1bcCJo3E5YJOw`, $0.038). Apify is not in the judged path: the skill runs with no keys at all.

Licence: MIT, see [`LICENSE`](LICENSE).
