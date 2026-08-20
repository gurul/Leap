# Learnings

The durable knowledge, organised by subject. The git log is already the
chronology; this is the part that outlives any particular version of the tool.

Everything here carries its source — a commit sha, a `file:line`, or a dated
research note in [`../context/`](../context/). If a claim has no source, it
does not belong on these pages.

Features come and go in this repo. The measurements do not.

## Find the right page in one hop

| You want to know | Page |
|---|---|
| Why a pose classifies the way it does; what the sensor actually reports; how hands are identified and lost | [hand-tracking.md](hand-tracking.md) |
| Why the cursor went where it went — planes, gain, the reach box, touch mapping, PRISM, the jitter hunt (**all shelved, all rich**) | [screen-mapping.md](screen-mapping.md) |
| Why the vocabulary is these poses and these dwells; the recurring bug shapes | [gesture-vocabulary.md](gesture-vocabulary.md) |
| Frame rates, the detection budget, the WebRTC path, what is worth optimising | [latency-and-pipeline.md](latency-and-pipeline.md) |
| Why the guard is a separate process; every path that releases held input | [safety-and-failure-modes.md](safety-and-failure-modes.md) |
| Coordinate spaces, event injection, TCC permissions, signal traps | [macos-platform.md](macos-platform.md) |
| How this project settles arguments with data — corpora, fitting rules, the bench, adversarial verification | [measurement-method.md](measurement-method.md) |
| What is shelved and the exact command to bring it back | [restoring.md](restoring.md) |
| What was tried and rejected — read before proposing | [dead-ends.md](dead-ends.md) |

## The five findings worth knowing before anything else

1. **A deliberate pinch reads as three extended fingers** — 100% of 443 corpus
   frames — so the lift threshold is 4, not 2. Lifting at 2 parks the cursor at
   the exact moment of every click. The single least obvious number in the
   system. ([interaction.md:28-32](../context/interaction.md), 15d5631)
2. **Raising gain fixed tracking.** Frame rate 36 → 116 fps, hand visible ~32%
   → ~100%, with no tracking parameter changed: higher gain means less hand
   travel, which keeps the hand in the reliable centre of the sensor cone.
   ([interaction.md:76-84](../context/interaction.md), 6fc79da)
3. **Poses you pass *through* are not poses.** The most repeated bug shape
   here: a fist opens thumb-first through a perfect thumbs-up; a pinch releases
   through the OK sign; a hand leaving the two-hand L passes through thumbs-up.
   Three separate live failures, two shadow mechanisms.
   ([gesture-vocabulary.md](gesture-vocabulary.md#poses-you-pass-through-are-not-poses))
4. **A shared release path invoked for a non-release reason** is the second
   most repeated shape: the clutch deadlock (63161f2), then `busy` faking a
   tracking loss — 17 of 21 clutch drops, zero from an actual hand loss
   (31297f3).
5. **The reach box is a different projection per engagement.** Across 65
   recorded clicks the box origin ranged 0.202 → 0.749 of the frame and its
   width 0.211 → 0.693 (zoom 1.4× → 4.7×). That is why absolute aim stopped
   being learnable. ([troubleshooting.md:94-110](../troubleshooting.md))

## How to read a page here

Each page is organised by mechanism, not by date. Claims are stated with the
measurement that produced them, and shelved material says so and links to
[restoring.md](restoring.md).

Where a page says **unfixed**, it means exactly that: confirmed real, never
fixed, recorded so nobody rediscovers it from scratch. The live list is in
[../context/hardening-2026-08-19.md](../context/hardening-2026-08-19.md#deferred--confirmed-real-needs-maintainer-sign-off)
and is summarised on the pages that own each finding.
