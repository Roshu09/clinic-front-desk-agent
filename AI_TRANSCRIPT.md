# AI transcript — how I directed the coding assistant

Assistant: Claude (Anthropic) in a coding/agent session. These are my prompts, verbatim and in order.
The assistant read the brief and starter pack itself, proposed the architecture, wrote the code and tests, and I reviewed and ran it.

1. `i applied for a role and got this assignemnt task via mail can you figuure out the assignment and help me in completionm`
   (attached the Gmail printout of the assignment email)
2. `this is the page i got after clicking assignment` (attached the assignment page printout)
3. `can you say in english`
4. (uploaded `swasthiq-front-desk-agent-starter-pack.zip` and `SwasthiQ-Hiring-Assignment-September2026.pdf`)
5. `go ahead`

6. `okay sorry i didnt understand well everything we can do the project understanding in after end completion of assifgnment . lets just focus now on making the assigmnent so here i understood what is you gave me a zip folder now named front desk agent right so now what i need to do with it . i mean how i should run it through terminal? . i mean give me steps . also i noticed you asking something for llm api so i can provide groq api if you will need leyt me know`
7. `is everything good till now please check . also you said this On Mac, Linux or Git Bash you can replace steps 2–4 with ./run.sh.. i didnt understand i have linux fedor distro so tell according to that further steps` (attached my terminal log of the install, build and server start)
8. `now tell next steps the groq one which one i need to stopterminal` (attached pytest and runner logs: 117 passed, failures 0)
9. (pasted my terminal after exporting the Groq variables and starting the server) then: `yeah actually it showed llm+rules but i closed all terminal tell me how to run again and i also havent run it yet  so also tell where to run` the benchmark and runner commands
10. `will i need to api key everytime while starting the server? i already done that but sent you cut optuput you already got that above`
11. a complaint that the config-file command did not say which folder to run it in (answer: any folder; `~` is home)
12. (pasted `source ~/.config/frontdesk.env` check, server start, and the first Groq benchmark where every row showed 0 tokens) `these all optputs of 4 different terminals tell me is all okay`
13. (pasted a direct curl to Groq: `model_not_found` for llama-3.3-70b-versatile; then the model list; then the working curl for `openai/gpt-oss-120b`) `did it work`
14. (pasted benchmark runs 2, 3, 4 and 5 as I fixed one problem at a time; pasted the diagnostics the assistant asked for, including the `expected 3 turn entries` error)
15. (pasted the final benchmark: all rows with tokens, `cv_0015` booked) and the runner results (`failures: 0`, deterministic)
16. `i have github account username is roshu09 ... tell me with which name i need to make new repo`; then the `gh auth login` and push steps, and `yes everything done i think push is done <repo url>`
17. (screenshots of the Render blueprint form, then of `/health` and the live dashboard), then the runner output against the live URL (`failures: 0`, deterministic)

## Problems found by running the real model, and how they were fixed

The rules-only agent passed everything from the start. Turning on `openai/gpt-oss-120b` through Groq exposed four problems that a fake model could not have shown me. Each one now has a regression test (122 tests in total).

| # | What I saw | Cause | Fix |
|---|---|---|---|
| 1 | Benchmark: 0 tokens on every row | Groq had retired the model I first tried (`llama-3.3-70b-versatile`), and the agent silently fell back to rules | Listed my key's models, switched to `openai/gpt-oss-120b`. Benchmark now prints the reason when a call fails. |
| 2 | Only 1 of 23 calls worked, others fell back | Groq free-tier tokens-per-minute limit | Retry on 429/5xx honouring `Retry-After`; ask gpt-oss for low reasoning effort |
| 3 | `cv_0006` turned into `rescheduled` (expected `booked`); later `cv_0015` turned into `abandoned` | The model read vague follow-ups ("toh 8 tareekh ko subah?", "toh 9:30 kar dijiye") as a reschedule, or put a stray time on a later turn | The model may only fill a field the rules never found anywhere in the conversation, and the only intent it may suggest is `book` (cancel and reschedule are destructive and need the rules' own evidence) |
| 4 | Three conversations fell back with `expected 3 turn entries` | The model returned a different number of turn entries than turns | Entries are matched by their own turn number; missing turns just get rules-only reading instead of discarding the whole reply |

## What I checked myself

* Ran `pytest` on my own Fedora machine (117 passed at that point, 122 after the fixes above).
* Ran the starter `runner.py` with `--repeat 3` on the 15 starter conversations and the 8 adversarial scripts, locally and again against the deployed URL: `failures: 0`, deterministic across 3 runs.
* Ran the token/latency benchmark against a real model (Groq, `openai/gpt-oss-120b`), noticed the 0-token rows and the changed outcomes myself, and sent the failing output back until each cause was found.
* Opened the dashboard locally and on the live URL, clicked into `adv_0008`, and compared the queue to the numbers from the runner.
* Created the GitHub repo, pushed, and deployed on Render myself.
* TODO before submitting: add here anything else you read or tried yourself, for example which parts of DECISIONS.md you read, and any phrasings of your own you typed into the agent.
