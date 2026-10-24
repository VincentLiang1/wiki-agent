# What is an LLM Wiki?

**English** | [繁體中文](What-is-LLM-Wiki.zh-TW.md) | [简体中文](What-is-LLM-Wiki.zh-CN.md)

**In one sentence: AI turns your meetings, documents and notes into a personal knowledge base that keeps growing on its own.**

## A problem you have probably had

Meeting notes, slide decks, contracts, reading notes, clippings… they usually go into a folder and are never looked at again. As a result:

- Finding something when you need it takes forever
- New information never connects with what you already have
- Who promised what at the last meeting lives only in someone's memory

## How an LLM Wiki solves it

The LLM Wiki is an approach proposed by AI expert Andrej Karpathy (former Director of AI at Tesla and a founding member of OpenAI): **let the AI be your "knowledge organizer."**

You just add material, and the AI will:

1. Read it and write clear notes pages with the key points
2. Add new material to the existing page when it is related, instead of starting a new one
3. Link pages to each other and keep an overall table of contents

The more you add and the more you ask, the more complete the knowledge base becomes. This is what he calls "knowledge that compounds."

## How is this different from just asking an AI?

An AI has read a lot of public material on the internet, but it **knows nothing about you**: your company's meetings, internal rules, clients and project status are things it has never seen. And every conversation starts from zero, so what you discussed last time is forgotten next time.

An LLM Wiki is like giving the AI **a handover notebook**:

| | Just asking an AI | With an LLM Wiki |
| --- | --- | --- |
| Knows about your work | No, it can only say "in general…" | Yes, answers come from your notes |
| Remembers next time | No | Yes, it is all written in the notes |
| Where answers come from | It cannot say | Every page cites its sources, so you can check |
| Over time | Stays the same | Gets more and more useful |

## What does the knowledge base look like?

It is simply a folder on your computer, with three parts:

- **Sources**: the recordings, transcripts and documents you add. The AI reads them but never changes them
- **Notes pages**: the pages the AI writes, plus an overall table of contents
- **Rules file**: tells the AI how to organize things (language, format, categories). The AI reads it before every job

Here is what the folders actually look like (Wiki Agent creates them when you install it):

```
Your knowledge base folder/       ← the outer folder; name it anything
├─ Raw_Sources/                   ← sources: recordings, transcripts, PDFs, slides
│  ├─ _Pending/                   ← new files land here first
│  └─ New product/                ← once processed, the original moves to a topic folder
└─ WIKI/                          ← the knowledge base itself
   ├─ CLAUDE.md                   ← rules file: how the AI organizes things
   └─ Wiki_Pages/                 ← the notes the AI writes
      ├─ index.md                 ← table of contents
      └─ New product/
         └─ 2026-10-20 Weekly.md  ← one page per meeting, linked to related pages

iCloud Drive/_WikiBox/            ← inbox: transcripts you Send from the phone arrive here
```

The notes are ordinary text files (Markdown) that any app can open. **Your data stays in your hands**: it is not locked into anyone's cloud service, and you can still read it ten years from now.

## What Notetaker + Wiki Agent do for you

Building an LLM Wiki yourself takes a fair amount of learning. With these two programs, you just press one button:

1. Notetaker on your iPhone records the meeting, turns it into a transcript, and you tap "Send"
2. The transcript goes to your computer through iCloud
3. Wiki Agent on your computer picks it up and asks Claude to file it into your knowledge base the LLM Wiki way
4. You get a daily summary email telling you what was filed

Besides meetings, you can drop whiteboard photos, scans and Office files into the same folder.

## What can you use it for?

- "What terms did we discuss in last month's three meetings with the vendor?" The AI looks it up in your notes and sums it up
- A project with a dozen meetings gets its full story and to-do list put together automatically
- A long thread of emails or discussions becomes one page that tells what happened
- Regulations and contracts get rewritten in plain language, with the parts that matter to your role marked

## Things to keep in mind

- **The AI can get things wrong**: the notes are written by AI, so check important numbers, names and dates against the sources
- **Choose what you add**: if you pour in lots of unrelated material, the AI may force connections between them
- **You need a paid Claude plan** (Pro or higher): filing uses your own Claude account and quota, and the content is processed by Anthropic. With a personal account, we suggest turning off "Help improve our AI models" under Claude's Settings › Privacy so your conversations are not used to train models
- **It is not a reason to stop reading**: Karpathy himself points out that the approach saves you the filing and bookkeeping, and the time you save should go into reading and thinking
