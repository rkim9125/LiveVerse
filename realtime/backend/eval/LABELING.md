# Labeling guide for sermon evaluation

These rules decide what counts as a correct answer when scoring the detector on recorded sermons. The labels live outside the repo, in `$LIVEVERSE_CORPUS/<sermon>/candidates.jsonl`. Only the scripts and this guide are committed.

## The main rule

A reference is correct only if the interpreter would have wanted to put it on the display at that moment.

Saying a book or chapter is not enough. The question is whether the congregation should see that passage now.

## What counts

| Situation | Label | Example (paraphrased) |
|---|---|---|
| The preacher announces a passage to read or look at | the passage | "Let's read John 3:16" → `jo 3:16` |
| A chapter is announced before its verses | both the chapter and the verse, as said | "Isaiah 40. Isaiah 40:27" → `is 40`, `is 40:27` |
| A relative mention ("verse 17", "the next verse") | the resolved passage | after `jo 3:16`, "verse 17" → `jo 3:17` |
| Consecutive verses said one after another | one range | "verses 19, 20" → `rt 2:19-20` |
| A range with a missing word ("verse 1, to verse 5") | one range | → `rt 3:1-5` |
| Non-consecutive verses | separate references | "verses 1 and 4" → `rt 4:1`, `rt 4:4` |
| The speech recognizer misheard the book name | the book the preacher meant | "룩기 2장" (meant 룻기) → `rt 2` |
| The speech recognizer misheard a number | the number the preacher meant | "사절" (meant 4절) → `rt 4:4` |
| A chapter of another book, and the preacher then reads from it or names a verse | the verse that was read or named, not the chapter. If the verse number is not said, find it from the words read | "2 Corinthians 11 says..." followed by the words of 11:2 → `2co 11:2` |
| At the close, the preacher reads one verse | that verse | "one last verse" then verse 28 is read → `ps 73:28` |
| A verse quoted word for word without its number ("as it is written, *the words of the verse*") | that verse, found from the quoted words | words of Ezekiel 36:37 quoted → `ez 36:37` |

## What does not count

| Situation | Why |
|---|---|
| Bookmark instructions ("keep a finger in Ruth 2 and turn to Psalm 139") | The interpreter shows Psalm 139, not Ruth 2 |
| Advice to read a whole book or several chapters ("read Malachi 1 to 4") | Not a passage to display |
| A book named without a chapter ("in the days of Malachi") | Nothing to display |
| A book name inside another word ("나오미가" contains 미가) | Not a reference |
| Words heard while the preacher reads the text aloud ("찬송할지로다") | Not a reference |
| Hymn numbers ("찬송가 305장") | Not Bible text |
| A number after a book that is not a chapter ("요한계시록의 7년 환란") | Not a reference |
| A chapter of another book, said in passing with no reading and no verse ("Matthew 24 and Revelation describe these times") | Nothing for the congregation to look at |
| A chapter said again while a verse of that chapter is already on the display ("Isaiah 40" after `is 40:27` is shown) | The display already shows that chapter. Keep the verse |
| The content of a passage retold in the preacher's own words ("1 Corinthians 15 says the sun, moon and stars differ in glory") | A paraphrase is not a quote. Only word-for-word quotes count |
| A general look back while a verse is on the display ("if you read from verse 1, the psalmist struggled...") | The preacher is summarizing. The correct answer is the verse already on the display |
| A chapter of the passage being preached, mentioned while retelling the story ("in chapter 2 we see God's blessing", "if you read chapter 3, Boaz decides to act", "chapter 1 starts in grief, but in chapter 4...") | The preacher is summarizing, not asking anyone to turn there. The same chapter does count when it is announced to open or read ("let's go back to Ruth 4 and read it together") |

## Chapter and verse duplicates

When a chapter and then a verse in that chapter are both said, both are correct. Merging them into one candidate is a display question, so it is counted separately and does not change precision or recall.

## Fields in candidates.jsonl

| Field | Meaning |
|---|---|
| `decision` | `accept` (detected refs are right), `fix` (correct_refs differ from what was detected) or `reject` (no reference in this window) |
| `correct_refs` | the right answer for this window, in fixture form: `jo 3`, `jo 3:16`, `jo 3:16-18` |
| `error_types` | why the detector was wrong, if it was (see below) |
| `label_source` | `claude-1st-pass` for a suggested label, `user` once a person has changed it |
| `notes` | free text for the reviewer |

Error types used so far: `stt-book-name`, `context-carryover`, `no-context`, `range-form`, `chapter-verse-duplicate`, `numeral-deny-list` and `bare-number`.

## Copyright and privacy

- Transcripts contain Bible text read aloud and the preacher's own words. They stay in the corpus folder.
- Reports from `eval/score.py` contain numbers only.
- If a mention becomes a fixture in `tests/fixtures/parser_cases.jsonl`, it is rewritten as a plain generic sentence that keeps only the pattern. No sermon text is copied.
