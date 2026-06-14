# ICSI Held-Out Future-Meeting Eval Pack

- status: `candidate_manual_review_required`
- generated at: `2026-06-14T07:33:00Z`
- source boundary: `Bmr023`
- query count: `20`
- candidate topic count: `145`

This pack is designed for manual review before professor-facing claims. Held-out BMR meetings are used only as future triggers; expected answers must come from the source-side share_mem snapshot.

## Manual Review Checklist

- Confirm the query is answerable from the source-side evidence only.
- Confirm held-out trigger evidence is not used as expected answer evidence.
- Confirm expected L2 labels are not filler, discourse markers, or generic buckets.
- Confirm the scoring rubric matches the query type.

## Candidate Questions

### icsi-heldout-q001 `evidence_lookup`

What concrete source-side evidence did the ICSI BMR meetings contain about resource allocation?

- expected L2: `resource allocation`
- expected L3: `project planning and management`
- source meetings: `Bmr001, Bmr002`
- held-out triggers: `Bmr024, Bmr025`
- source evidence:
  - `L1-Bmr001-052` `Bmr001` Although speaker location detection has been proposed as a research angle and is considered feasible with the available data, it is unresolved who will write the necessary software to implement it.
  - `L1-Bmr002-031` `Bmr002` The project team needs to define the process for transcribing meetings for training and testing, which includes creating word transcripts and identifying speaker changes. Key decisions to be made are who will perform the transcription, what tools and resources to use, and what data format to follow.
  - `L1-Bmr002-059` `Bmr002` It was decided that a single person will not be responsible for all transcription work, given the anticipated volume of a couple of hours of recording per week. This implies that other resources, such as students or commercial services, will be needed.
- held-out trigger examples:
  - `L1-Bmr024-108` `Bmr024` Handling non-standard recordings as a special case, rather than integrating them into the standard processing pipeline, is problematic because it leaves the question of who will perform the required work unanswered.
  - `L1-Bmr024-109` `Bmr024` If non-standard recordings are to be handled as a special case, it is not yet determined who will be responsible for doing the work.
  - `L1-Bmr025-117` `Bmr025` The team will keep the CrossPads for another year for exploratory use, even without implementing the full supporting infrastructure.

### icsi-heldout-q002 `topic_evolution`

Before the held-out meetings, how had disk space evolved across the ICSI BMR discussions?

- expected L2: `disk space`
- expected L3: `corpus design and data management`
- source meetings: `Bmr001`
- held-out triggers: `Bmr024, Bmr025`
- source evidence:
  - `L1-Bmr001-085` `Bmr001` The team decided to purchase a new 40-50 GB drive for waveform data storage, as repartitioning the existing drive was considered too difficult and would require a full data backup and restore.
  - `L1-Bmr001-099` `Bmr001` A counter-argument to deleting the Broadcast News data is that the 12GB of space gained would only accommodate a "couple hours" of new recordings, making it an insignificant, short-term solution.
  - `L1-Bmr001-100` `Bmr001` The Broadcast News dataset is approximately 12 gigabytes in size, which is equivalent to about 20 CDs.
- held-out trigger examples:
  - `L1-Bmr024-097` `Bmr024` A decision was made to save all recorded data, including from distant microphones, because it is potentially useful for future work and disk space is inexpensive.
  - `L1-Bmr024-129` `Bmr024` An ongoing plan is in place to acquire an additional file server to address the need for more disk space.
  - `L1-Bmr025-086` `Bmr025` Acquire more disk space, which is a prerequisite for beginning meeting recording.

### icsi-heldout-q003 `decision_rationale`

What decisions or rationale were established about audio processing before the later BMR meetings revisited it?

- expected L2: `audio processing`
- expected L3: `audio acquisition and signal processing`
- source meetings: `Bmr001`
- held-out triggers: `Bmr024`
- source evidence:
  - `L1-Bmr001-046` `Bmr001` As an alternative to 'delay and sum' beamforming, which is not optimal for non-planar wavefronts in the near-field, it is proposed that microphones should be placed as close together as possible. This counter-intuitive approach is reportedly used in underwater acoustics.
  - `L1-Bmr001-047` `Bmr001` Advanced beamforming techniques, unlike simple delay-and-sum methods, perform better when the microphones in an array are placed as close together as possible.
  - `L1-Bmr001-053` `Bmr001` It was proposed to explore sophisticated approaches for processing data from two microphones, despite the expectation that simple methods would be difficult and that reviewers might be skeptical of two-microphone setups.
- held-out trigger examples:
  - `L1-Bmr024-013` `Bmr024` A new audio format was adopted for transcription, inserting a "beep [spoken digit] beep" sequence between phrases. This format was applied to the automatic segmentations and sent to IBM.
  - `L1-Bmr024-068` `Bmr024` The potential problem of beeps interspersed with digits in the audio is not considered a significant obstacle for transcription, as the beeps are distinct and pre-recorded, and it is expected that transcribers will use macros to insert beep markers.
  - `L1-Bmr024-194` `Bmr024` A low-pass filter was implemented to band-limit the audio signal at approximately 3700 Hz, a practice common in Hub-five systems. This change proved beneficial and did not negatively affect male speaker data.

### icsi-heldout-q004 `next_meeting_carryover`

What context about speech recognition should be carried into later BMR meetings?

- expected L2: `speech recognition`
- expected L3: `asr modeling and evaluation`
- source meetings: `Bmr002, Bmr003`
- held-out triggers: `Bmr024, Bmr025, Bmr026`
- source evidence:
  - `L1-Bmr002-203` `Bmr002` Training a recognizer requires tens of hours of labeled data, which poses a significant and unresolved resource challenge for the project.
  - `L1-Bmr002-205` `Bmr002` The MARSEC project is proposed as a potential source of training data, as it contains time-aligned spoken data with rich intonational and stress-oriented transcription, a combination not often found together.
  - `L1-Bmr003-099` `Bmr003` The current transcription tool does not have speech recognition capabilities.
- held-out trigger examples:
  - `L1-Bmr024-201` `Bmr024` There is an unexplained 1-2% performance degradation for female speakers when using ICSI features compared to the standard SRI system, even with VTL normalization. The cause for this discrepancy is unknown and suggestions are sought.
  - `L1-Bmr025-146` `Bmr025` There is ongoing research involving recognition runs to understand certain features, but the work is still in process and no conclusions have been reached yet.
  - `L1-Bmr025-147` `Bmr025` Recognition runs are in progress by several team members to analyze features, but there are no reportable results yet.

### icsi-heldout-q005 `corpus_process`

What does the source-side BMR corpus reveal about the process or workflow around annotation tool?

- expected L2: `annotation tool`
- expected L3: `annotation and transcription workflow`
- source meetings: `Bmr002`
- held-out triggers: `Bmr024, Bmr025`
- source evidence:
  - `L1-Bmr002-093` `Bmr002` Investigate the annotation tools published by Mississippi State.
  - `L1-Bmr002-094` `Bmr002` The project needs to select an annotation tool. Tools from Mississippi State and XWaves have been suggested as potential options, with XWaves noted as being low-level but potentially useful for marking speaker changes.
  - `L1-Bmr002-095` `Bmr002` XWaves was proposed as a potential annotation tool, noted as being 'low level' and suitable for phoneme-level transcription and marking speaker changes.
- held-out trigger examples:
  - `L1-Bmr024-047` `Bmr024` A new transcription workflow has been implemented which provides transcribers with a visual representation of the audio waveform. Transcribers are trained to quickly scroll through this visual display to find small audio events, such as backchannels, that were missed by the automated pre-segmentation process.
  - `L1-Bmr025-067` `Bmr025` To prevent missing data, it is proposed that annotators use the 'Edit-key' tool for editing Key files instead of a plain text editor, as the tool provides specific fields for required information like seat numbers.
  - `L1-Bmr025-069` `Bmr025` The failure to record seat information in Key files is identified as a process failure resulting from annotators using plain text editors. The recommended 'Edit-key' tool, which was previously offered but declined, includes a dedicated field that would have prevented this omission.

### icsi-heldout-q006 `evidence_lookup`

What concrete source-side evidence did the ICSI BMR meetings contain about acoustic modeling?

- expected L2: `acoustic modeling`
- expected L3: `asr modeling and evaluation`
- source meetings: `Bmr002, Bmr005`
- held-out triggers: `Bmr024`
- source evidence:
  - `L1-Bmr002-197` `Bmr002` The data collection effort is for the purpose of building general English acoustic models for the SmartKom project.
  - `L1-Bmr002-239` `Bmr002` The data collection process is stopped using the Control-C command.
  - `L1-Bmr005-148` `Bmr005` To improve efficiency, the team will use automated scripts to extract and transcribe digit reading utterances, replacing the previous process of having external groups perform the task. The acoustics work for the Meeting Recorder will start with this automatically processed data.
- held-out trigger examples:
  - `L1-Bmr024-121` `Bmr024` It is an open question whether to use available recordings of American-born speakers reading German place names for acoustic modeling, as doubts have been expressed about the desirability of this data.
  - `L1-Bmr024-122` `Bmr024` A suggestion was made to use recordings of American-born people reading German place names for acoustic modeling.
  - `L1-Bmr024-212` `Bmr024` It was resolved that likelihoods from different model sets, such as those from PLP versus mel cepstrum, cannot be directly compared because each model is trained with a different normalization constant.

### icsi-heldout-q007 `topic_evolution`

Before the held-out meetings, how had audio quality evolved across the ICSI BMR discussions?

- expected L2: `audio quality`
- expected L3: `audio acquisition and signal processing`
- source meetings: `Bmr001`
- held-out triggers: `Bmr024, Bmr027`
- source evidence:
  - `L1-Bmr001-034` `Bmr001` A 'build vs. buy' decision is needed for a pre-amplifier to solve a significant noise and amplification problem with the wired headsets. The current custom-built pre-amp is too noisy, but a custom solution is considered necessary for future PDA integration, and no single commercial unit provides all needed functionality.
  - `L1-Bmr001-042` `Bmr001` The custom-built pre-amp for wired headsets has significant flaws, including being too noisy for use, clumsy, requiring batteries for bias, supporting only two channels, and having too many connectors.
  - `L1-Bmr001-065` `Bmr001` It is hypothesized that the audio quality from the wired microphones will be acceptable for recording.
- held-out trigger examples:
  - `L1-Bmr024-022` `Bmr024` It is hypothesized that the observed 'split-beep' artifact is a playback issue, possibly due to audio device latency or 'hiccups', and not a defect in the source audio file.
  - `L1-Bmr024-023` `Bmr024` It was proposed to investigate the 'split-beep' issue by listening directly to the source audio files to verify the problem.
  - `L1-Bmr027-002` `Bmr027` The overall audio quality of the "ear-plug mike" is unknown and needs to be evaluated, although its signal level is considered acceptable.

### icsi-heldout-q008 `decision_rationale`

What decisions or rationale were established about meeting agenda before the later BMR meetings revisited it?

- expected L2: `meeting agenda`
- expected L3: `project planning and management`
- source meetings: `Bmr002, Bmr003, Bmr006`
- held-out triggers: `Bmr024`
- source evidence:
  - `L1-Bmr002-170` `Bmr002` The discussion on intonation contours will be deferred to a future meeting, possibly with Liz.
  - `L1-Bmr003-003` `Bmr003` It was determined that participant Dave (me904) did not need to attend the meeting, as the topic was focused on transcription for future meetings.
  - `L1-Bmr006-294` `Bmr006` A proposal was made to discuss "thresholding stuff", with the option to postpone the topic if time was short.
- held-out trigger examples:
  - `L1-Bmr024-001` `Bmr024` The group needs to discuss the ARPA demo, a topic Morgan wanted to address.
  - `L1-Bmr024-005` `Bmr024` A proposal was made to discuss adding the SmartKom dataset to the Meeting Recorder corpus.
  - `L1-Bmr024-007` `Bmr024` A proposal was made to discuss 'Absinthe,' a multiprocessor Linux system.

### icsi-heldout-q009 `next_meeting_carryover`

What context about meeting recorder should be carried into later BMR meetings?

- expected L2: `meeting recorder`
- expected L3: `project planning and management`
- source meetings: `Bmr001, Bmr002`
- held-out triggers: `Bmr025, Bmr026`
- source evidence:
  - `L1-Bmr001-122` `Bmr001` The initial data collection plan is to begin by recording the Meeting Recorder team's own meetings, and then potentially expand to other internal speech groups like the AI and Decoder teams.
  - `L1-Bmr002-161` `Bmr002` The team will begin collecting potential user queries for the Meeting Recorder system. Team members are instructed to imagine the system is complete and write down questions they would ask about meeting content.
  - `L1-Bmr002-162` `Bmr002` The specific user queries that the Meeting Recorder system should support are currently undefined, representing a key open issue for system design. To address this, team members have been asked to start collecting potential queries they would pose to the system.
- held-out trigger examples:
  - `L1-Bmr025-084` `Bmr025` The initial plan to store Meeting Recorder data on non-backed-up disk space was rejected; this space will be reserved for data that is easily recreatable.
  - `L1-Bmr025-088` `Bmr025` The backup strategy for Meeting Recorder data was changed to a dual-modality approach for redundancy. The data will now be included in the standard backup system and also manually copied via 'NW archive', rejecting a previous idea to use non-backed-up disk.
  - `L1-Bmr026-024` `Bmr026` The team has decided to publish their custom Windows NT version of Transcriber on the Meeting Recorder webpage.

### icsi-heldout-q010 `corpus_process`

What does the source-side BMR corpus reveal about the process or workflow around far field?

- expected L2: `far field`
- expected L3: `audio acquisition and signal processing`
- source meetings: `Bmr002, Bmr003`
- held-out triggers: `Bmr024, Bmr028`
- source evidence:
  - `L1-Bmr002-187` `Bmr002` If a speech recognizer is built for the project, it must be trained on the far-field microphone data, as solving the far-field problem is a core project goal.
  - `L1-Bmr002-198` `Bmr002` The data collection will be conducted using far-field microphones.
  - `L1-Bmr002-200` `Bmr002` The data collection methodology involves the use of far-field microphones.
- held-out trigger examples:
  - `L1-Bmr024-095` `Bmr024` The recording protocol was changed to save all far-field audio channels, reversing an initial plan to discard them. This decision was made to support potential future acoustic studies and to maintain consistency across recordings.
  - `L1-Bmr024-096` `Bmr024` Despite an initial plan not to save far-field data, it was determined that all far-field channels should be saved to support potential future acoustic studies and to ensure consistency across all recordings.
  - `L1-Bmr028-250` `Bmr028` Text transcribed from problematic far-field microphone recordings could be used for other purposes, such as language modeling.

### icsi-heldout-q011 `evidence_lookup`

What concrete source-side evidence did the ICSI BMR meetings contain about error analysis?

- expected L2: `error analysis`
- expected L3: `asr modeling and evaluation`
- source meetings: `Bmr003, Bmr006, Bmr016`
- held-out triggers: `Bmr025, Bmr027, Bmr028`
- source evidence:
  - `L1-Bmr003-336` `Bmr003` An evaluation concluded there were 'no direct driver errors,' but a speaker's attempt to explain a mistake she made was cut off during the session.
  - `L1-Bmr006-263` `Bmr006` The team has adopted a framework for analyzing failures in the two-microphone speaker localization system, categorizing them into two types: "pathological errors," which occur when a speaker is positioned directly in line with the two microphones, and "sensitivity issues," which occur when two speakers are too close together.
  - `L1-Bmr016-079` `Bmr016` Preliminary ASR results indicate that recognition errors are primarily caused by speaker overlap, not by differences in speaking style.
- held-out trigger examples:
  - `L1-Bmr025-134` `Bmr025` A PDA is considered technically superior to a CrossPad for data capture because its data is natively digital. This avoids the potentially error-prone conversion from the CrossPad's non-standard, pixel-based format, which does not perform handwriting recognition.
  - `L1-Bmr027-143` `Bmr027` A review of transcription quality revealed common error patterns, including syntactically incorrect phrases (e.g., 'little too much' for 'we learned too much') and misheard words (e.g., 'bad master' for 'web master').
  - `L1-Bmr027-154` `Bmr027` Transcription errors were found to be caused by jargon, sometimes combined with a foreign accent, rather than by acoustically challenging audio.

### icsi-heldout-q012 `topic_evolution`

Before the held-out meetings, how had audio file evolved across the ICSI BMR discussions?

- expected L2: `audio file`
- expected L3: `corpus design and data management`
- source meetings: `Bmr001, Bmr002`
- held-out triggers: `Bmr025, Bmr027`
- source evidence:
  - `L1-Bmr001-104` `Bmr001` The project's audio files are uncompressed and contain sections of silence, resulting in large file sizes.
  - `L1-Bmr002-044` `Bmr002` The team will use configurable PC foot pedals for transcription work. This approach avoids the need to convert digital audio files to cassettes for a traditional transcription machine, while still providing an ergonomic interface. The pedals function by connecting to a computer and generating configurable keystrokes.
  - `L1-Bmr002-046` `Bmr002` It was proposed to use a software-based tool for transcription, since the audio files are already in a digital format.
- held-out trigger examples:
  - `L1-Bmr025-019` `Bmr025` The front-end of the new search tool is being adapted for meeting data by porting it to UNIX and rewriting it to handle a single large audio file and differentiate between speakers, instead of many small files.
  - `L1-Bmr027-097` `Bmr027` After an audio file is successfully redacted, the original version will be archived and removed from the active system.
  - `L1-Bmr027-135` `Bmr027` The team has provided the University of Washington (UW) with transcripts for six meetings and the corresponding audio files.

### icsi-heldout-q013 `decision_rationale`

What decisions or rationale were established about signal processing before the later BMR meetings revisited it?

- expected L2: `signal processing`
- expected L3: `audio acquisition and signal processing`
- source meetings: `Bmr001, Bmr006`
- held-out triggers: `Bmr024, Bmr028`
- source evidence:
  - `L1-Bmr001-045` `Bmr001` There is an unresolved question regarding the optimal signal processing approach for near-field microphone arrays, as simple delay-and-sum beamforming is considered suboptimal. More advanced, but not fully understood, techniques exist, some of which counter-intuitively suggest placing microphones as close together as possible.
  - `L1-Bmr001-054` `Bmr001` The assertion that "one cannot get much out of two microphones" is interpreted as a challenge for simple approaches, implying that more sophisticated methods could still yield interesting results, thus justifying continued research in this area.
  - `L1-Bmr001-103` `Bmr001` To address large audio file sizes, it was proposed to use 'Shorten', a lossless compression tool, which works by applying AR modeling and quantizing the residual.
- held-out trigger examples:
  - `L1-Bmr024-237` `Bmr024` There is an unresolved discrepancy in how the data is being viewed, which may be related to differences in signal processing, but the exact cause is unknown.
  - `L1-Bmr028-165` `Bmr028` To recover speech that was accidentally eliminated by a 'phase stuff' filter, an approach of inverting the filtering process was suggested.
  - `L1-Bmr028-166` `Bmr028` It was proposed that the speech removal process could be used to generate noise estimates and calculate signal-to-noise ratios.

### icsi-heldout-q014 `next_meeting_carryover`

What context about broadcast news should be carried into later BMR meetings?

- expected L2: `broadcast news`
- expected L3: `corpus design and data management`
- source meetings: `Bmr001, Bmr006`
- held-out triggers: `Bmr024, Bmr026`
- source evidence:
  - `L1-Bmr001-095` `Bmr001` Send an email to the 'speech local' mailing list to determine if the Broadcast News data is still in use, as it is being considered for deletion to free up server space.
  - `L1-Bmr001-098` `Bmr001` An argument for deleting the Broadcast News dataset is that it may no longer be in use, which would free up server space for new data.
  - `L1-Bmr006-106` `Bmr006` To free up disk space for new meeting recordings, Broadcast News Pfiles are being archived to tape and then deleted from the primary disk.
- held-out trigger examples:
  - `L1-Bmr024-234` `Bmr024` The system will be tested on noisy data, such as Broadcast News, to assess whether the findings generalize across different datasets.
  - `L1-Bmr024-238` `Bmr024` To ensure that findings are generalizable, the system should be tested on noisy data, like Broadcast News, to see if the conclusions are valid across different datasets.
  - `L1-Bmr026-112` `Bmr026` To improve performance for Hub-five training, the team will expand the training dataset by incorporating more read speech, including a larger subset of the Macrophone database and data from "focus condition zero from Hub-four from Broadcast News".

### icsi-heldout-q015 `corpus_process`

What does the source-side BMR corpus reveal about the process or workflow around user interface?

- expected L2: `user interface`
- expected L3: `annotation and transcription workflow`
- source meetings: `Bmr003`
- held-out triggers: `Bmr025`
- source evidence:
  - `L1-Bmr003-169` `Bmr003` The transcription tool's interface can display overlapping speakers, link the transcript to the audio, and play the audio for a selected utterance.
  - `L1-Bmr003-173` `Bmr003` The French transcription software will be updated in a future version to support an interface for more speakers.
  - `L1-Bmr003-182` `Bmr003` It remains undecided whether the implementation effort to add analog inputs (like foot pedals, joysticks, or mice) for variable speed control in the transcription tool is worthwhile.
- held-out trigger examples:
  - `L1-Bmr025-015` `Bmr025` The project will use the Tcl-TK THISL GUI from the Broadcast News project for its user interface, chosen for its ease of porting to Windows over a more complex web-based alternative.
  - `L1-Bmr025-016` `Bmr025` A decision is needed on which tool to use for a new, 'prettier' user interface. The options are a complex, web-based tool from SoftSound that is difficult to port to Windows, or a Tcl-TK GUI from Broadcast News, which is recommended as being easier to port.
  - `L1-Bmr025-039` `Bmr025` A new "running transcript" feature will be developed to display transcriptions from speaker to speaker. This requires designing a new user interface and investigating how to make it compatible with short segments.

### icsi-heldout-q016 `evidence_lookup`

What concrete source-side evidence did the ICSI BMR meetings contain about experimental setup?

- expected L2: `experimental setup`
- source meetings: `Bmr006, Bmr007`
- held-out triggers: `Bmr026, Bmr028, Bmr029`
- source evidence:
  - `L1-Bmr006-251` `Bmr006` Source localization with the PDA is difficult when a speaker is on the axis of the two microphones, as this reduces left-right differentiation. A turntable was suggested as a potential solution.
  - `L1-Bmr006-252` `Bmr006` To mitigate source localization issues when a speaker is on the axis of the PDA's microphones, it was suggested to place the device on a turntable.
  - `L1-Bmr006-272` `Bmr006` A proposed research goal is to investigate what is possible in a 'simulated normal situation' where only one person in a group has a PDA for recording.
- held-out trigger examples:
  - `L1-Bmr026-152` `Bmr026` Initial model training will be gender-dependent, starting with the small training set of approximately 30 hours per gender.
  - `L1-Bmr026-153` `Bmr026` A speaker will begin model training using the small training set (approx. 30 hours per gender) and needs to determine the appropriate network size for the task.
  - `L1-Bmr028-225` `Bmr028` The term 'cheating' is used colloquially to describe a flawed experimental design, but it can be perceived as pejorative. This suggests the term should be used with caution as its intended meaning—a critique of the experimental setup, not the data—may not be universally understood.

### icsi-heldout-q017 `topic_evolution`

Before the held-out meetings, how had conversational speech evolved across the ICSI BMR discussions?

- expected L2: `conversational speech`
- source meetings: `Bmr003, Bmr013`
- held-out triggers: `Bmr026, Bmr028`
- source evidence:
  - `L1-Bmr003-096` `Bmr003` The team has previously considered and decided against integrating an automatic speech recognizer (ASR) into the transcription tool, based on the expectation that the recognition quality for conversational speech would be too poor.
  - `L1-Bmr013-040` `Bmr013` A simple mapping from a phone to its corresponding articulatory features is inaccurate for conversational speech due to overlapping processes like voicing and nasality. The actual phonetic realization is more complex than a discrete sequence of phones.
  - `L1-Bmr013-046` `Bmr013` A pilot study is proposed to compare a small subset of conversational speech with a small subset of digit speech to evaluate a method's performance on predictable vs. non-predictable speech.
- held-out trigger examples:
  - `L1-Bmr026-108` `Bmr026` For digit recognition models, the training data will be optimized by removing conversational speech, which has no performance penalty, and including additional read speech, which improves performance.
  - `L1-Bmr026-110` `Bmr026` For training a digit recognizer, it is beneficial to add more read speech data, but conversational speech data can be removed without any performance penalty.
  - `L1-Bmr026-136` `Bmr026` The proposed context-independent system for conversational speech is expected to underperform, leaving an open challenge in matching the performance of the existing Broadcast News system.

### icsi-heldout-q018 `decision_rationale`

What decisions or rationale were established about user feedback before the later BMR meetings revisited it?

- expected L2: `user feedback`
- source meetings: `Bmr018, Bmr021`
- held-out triggers: `Bmr025, Bmr028`
- source evidence:
  - `L1-Bmr018-173` `Bmr018` A proposal is under consideration to switch to new microphones due to stability issues with the current models. While the new microphones are acoustically good, their adoption is contingent on user comfort, as mixed feedback suggests they may not be suitable for everyone.
  - `L1-Bmr021-004` `Bmr021` Despite reports that some users dislike the Crown microphones, several meeting participants stated they prefer them, indicating that user preference is divided and may be subjective (e.g., dependent on head shape).
- held-out trigger examples:
  - `L1-Bmr025-080` `Bmr025` It was suggested that the microphones themselves could have physical indicators, such as LEDs or a buzzer, to signal connection issues.
  - `L1-Bmr028-046` `Bmr028` Liz is to review the working solution for the UI features and request any necessary changes.
  - `L1-Bmr028-059` `Bmr028` Users report that it is difficult to find specific content in transcripts, including remembered misstatements, even when using keyword search.

### icsi-heldout-q019 `next_meeting_carryover`

What context about digit reading task should be carried into later BMR meetings?

- expected L2: `digit reading task`
- expected L3: `corpus design and data management`
- source meetings: `Bmr002`
- held-out triggers: `Bmr024, Bmr028`
- source evidence:
  - `L1-Bmr002-020` `Bmr002` Speakers are instructed to pause briefly between each line of numbers in the digit reading task to help transcribers distinguish between sequences.
  - `L1-Bmr002-021` `Bmr002` The protocol for the digit reading task specifies that speakers should read sentence-structured number sequences, pause briefly between lines for transcription clarity, and are free to use any intonation, with a suggestion to read them like a phone number.
  - `L1-Bmr002-022` `Bmr002` While any intonation is permitted for the digit reading task, it was suggested that reading them like a phone number is a good approach, implying this is a natural and easy way for speakers to perform the task.
- held-out trigger examples:
  - `L1-Bmr024-055` `Bmr024` A large amount of recorded digit-reading data remains untranscribed, with only a subset processed so far.
  - `L1-Bmr024-115` `Bmr024` Adopted a unified internal procedure and directory structure for storing different data types, such as meetings and digit reading tasks. A metadata flag within each file will be used to distinguish the interaction type. This approach was chosen for simplicity, with the strict condition that data is not semantically mislabeled (e.g., 'reading digits' must not be labeled as a 'meeting').
  - `L1-Bmr024-250` `Bmr024` The group adopted a unison digits reading task protocol where all participants read simultaneously to save time. The procedure is to first read the transcript number, then read the digit lines with a short pause between each line.

### icsi-heldout-q020 `corpus_process`

What does the source-side BMR corpus reveal about the process or workflow around forced alignment?

- expected L2: `forced alignment`
- expected L3: `annotation and transcription workflow`
- source meetings: `Bmr002, Bmr009`
- held-out triggers: `Bmr024`
- source evidence:
  - `L1-Bmr002-092` `Bmr002` To obtain utterance start and end times, one option is to have transcribers provide them, though this may require specific software. An alternative is to use forced alignment to generate the timestamps later.
  - `L1-Bmr009-098` `Bmr009` The annotation workflow will rely on automatically generated time marks derived from forced alignment of words, rather than requiring annotators to create them manually. Annotators will then classify the frames within these inherited time boundaries.
  - `L1-Bmr009-099` `Bmr009` A proposed workflow for annotation involves automatically generating time marks for words using a method like forced alignment, which would then be used as boundaries for classifying the audio frames within them.
- held-out trigger examples:
  - `L1-Bmr024-053` `Bmr024` Use forced alignment to help transcribe the large volume of digit-reading data.
  - `L1-Bmr024-054` `Bmr024` Forced alignment alone is considered insufficient for transcribing the digit-reading data due to the presence of speaker self-corrections in the recordings.
  - `L1-Bmr024-056` `Bmr024` An unresolved question exists on the best method for transcribing digits to get a 'clean' set. The options are forced alignment against the known script versus using a speech recognizer. The core uncertainty is whether the error rate from speaker mistakes is higher than the potential 1% word error rate of a recognizer, which would make forced alignment less reliable.
