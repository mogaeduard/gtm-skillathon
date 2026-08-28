# Sources — prospect input files

## Prospects (prospects.csv, prospects-all.csv)

**Provenance (Apify run, verbatim):**

- Actor: `compass/crawler-google-places` (actor id `nwua9Gu5YrADL7ZDj`, build `0.14.747`)
- Run id: `fRPr1bcCJo3E5YJOw`
- Dataset id: `iahO6eJ1cgBbiwIrS`
- Started: `2026-08-28T15:48:25Z` — Finished: `2026-08-28T15:48:37Z` (12.4 s)
- Cost: USD 0.03785
- Input:
  ```json
  {"searchStringsArray":["software company"],"locationQuery":"București, România","maxCrawledPlacesPerSearch":40,"language":"ro","skipClosedPlaces":true,"scrapeReviewsPersonalData":false,"maxReviews":0,"maxImages":0}
  ```
- Result: 40 places returned, 37 with a website, 36 unique domains.

**Retrieval date/time:**

- UTC: 2026-08-28T15:48:37Z (run finish)
- Europe/Bucharest (UTC+3): 2026-08-28 18:48:37

**What was stripped, and why:**

Phone numbers, emails, contact fields, review text, and `peopleAlsoSearch` data were stripped from the raw Apify dataset before saving `maps_clean.csv` / `maps_clean.json`. This is a hard event rule: no personal data. Only company-level fields were kept: `name, domain, website, category, rating, reviews, maps_url`.

**Reachability check:**

A reachability check was run at ~15:55 UTC with `curl`, one HEAD/GET request per domain. Result: 19/20 HTTP 200. `ro.realworld-systems.com` was unreachable and is excluded from `prospects-all.csv` (see below).

**Company-level public business listings only. The live run re-fetches every domain; these files are the input, never the evidence.**

### Exclusions

- `ro.realworld-systems.com` — excluded from `prospects-all.csv` (unreachable in the reachability check above).

## Customers (customers.csv)

**Source:** https://apify.com/success-stories (Apify's public customer success stories page), retrieved 2026-08-28 ~16:05 UTC (2026-08-28 19:05 Europe/Bucharest).

**Method:** company names read from the logo `alt` attributes and success-story cards on that page; each story page under `blog.apify.com` was opened to find the customer's own website; every domain was then verified with a live `curl` (HTTP 200 and the company name present in the page title or first 3 KB of text). Unverifiable or ambiguous names were dropped.

**Dropped:** individual people's names shown on the page (testimonial authors) and single-word logos that could not be resolved to a verified company website (Bloom, Cockpit, Hintly, Loyaltie, EU).

**Why Apify:** the event's own sponsor is used as the worked example because its customer list is public and every claim in this repository can be checked by the jury from the same page. The skill takes any `company,domain` CSV, including a CRM export or a published Google Sheet URL.

Company level public information only. No people, no emails, no profiles. The live run re fetches every domain.

## Declared ICP (icp-declared.md)

Retrieved 2026-08-28T16:07Z from https://apify.com/use-cases, https://apify.com/pricing, https://apify.com/enterprise. Paraphrased from the public pages; quoted phrases are marked as quotes.
