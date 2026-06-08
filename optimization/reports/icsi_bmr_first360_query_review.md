# ICSI BMR First360 Retrieval Query Review

- generated at: `2026-06-08T20:15:32Z`
- query count: `12`
- active L2 count: `134`
- suppressed L2 count: `5`

These queries are generated from active effective L2 topics. They are for retrieval trace review, not final professor-facing scoring until manually approved.

## Queries

### icsi-q001: What did the ICSI BMR meetings discuss about data quality?
- expected L2 labels: data quality
- representative L1:
  - `L1-Bmr001_first360-036` Bmr001_first360: A 'damp machine' is being used as a temporary pre-amplifier for recordings as a workaround for the high noise levels of the custom-built pre-amp.
  - `L1-Bmr002_first360-003` Bmr002_first360: There is a persistent "off-by-one" error between microphone numbers and their corresponding zero-based channel numbers, causing confusion during data collection. No official group procedure has been adopted to resolve th
  - `L1-Bmr002_first360-006` Bmr002_first360: Allowing users to freely adjust headset microphones for comfort is the preferred approach, despite the acknowledged risk of inconsistent audio levels if the user moves their head. The tradeoff is accepted for better user
  - `L1-Bmr002_first360-007` Bmr002_first360: A user observed that the headset microphone moves along with head movements, a characteristic that was accepted as normal for the equipment.

### icsi-q002: ICSI BMR meetings discussed data collection. How did that topic evolve across meetings?
- expected L2 labels: data collection
- representative L1:
  - `L1-Bmr001_first360-065` Bmr001_first360: The project will proceed based on the decision that the scenario of multiple co-located PDAs is a common, general-use phenomenon, making it a valid basis for research into distributed microphone arrays.
  - `L1-Bmr001_first360-069` Bmr001_first360: The scenario of multiple PDAs being present in one location is a believable and increasingly common general phenomenon, not one specific to technically-inclined groups, which justifies developing technology for it.
  - `L1-Bmr002_first360-023` Bmr002_first360: The team will conduct another digit reading session at the end of the meeting to collect more data.
  - `L1-Bmr003_first360-011` Bmr003_first360: There is an open question about when the planned 'alphabet' data collection task will be conducted.

### icsi-q003: What concrete evidence do the ICSI BMR meetings contain about corpus design?
- expected L2 labels: corpus design
- representative L1:
  - `L1-Bmr006_first360-021` Bmr006_first360: For acoustic-oriented research, there is a strong need to collect data from a large and diverse set of speakers, rather than focusing on a small group over time. Including many 'random scattered meetings' with various gr
  - `L1-Bmr006_first360-026` Bmr006_first360: The rationale for recording pre-existing, goal-oriented meetings is that they provide more valuable and structured data compared to recordings of 'random people talking'.
  - `L1-Bmr006_first360-041` Bmr006_first360: The networking group is a specific case for data collection as it is composed almost entirely of non-native English speakers (German and Spanish).
  - `L1-Bmr012_first360-009` Bmr012_first360: Add a 'recording date' field to the speaker form to provide context for the 'age' field, which is being kept on the form.

### icsi-q004: What did the ICSI BMR meetings discuss about audio processing?
- expected L2 labels: audio processing
- representative L1:
  - `L1-Bmr001_first360-046` Bmr001_first360: There is an unresolved technical debate on whether multiple microphones spaced less than three feet apart are effective for noise cancellation. A claim from a DARPA meeting stated they are 'totally useless', but this was
  - `L1-Bmr001_first360-048` Bmr001_first360: The ineffectiveness of simple delay-and-sum algorithms for near-field audio presents a technical challenge. An open question is how to apply advanced, counter-intuitive beamforming techniques, such as placing microphones
  - `L1-Bmr001_first360-049` Bmr001_first360: An advanced beamforming technique, reportedly from underwater acoustics, suggests placing microphones as close together as possible, which is counter-intuitive to traditional methods that rely on separation by distance.
  - `L1-Bmr001_first360-050` Bmr001_first360: In near-field audio, where sound wavefronts are not planar, simple delay-and-sum beam steering algorithms are ineffective. The 'near-field' condition relates to the distance from the sound source to the microphones, not

### icsi-q005: ICSI BMR meetings discussed meeting agenda. How did that topic evolve across meetings?
- expected L2 labels: meeting agenda
- representative L1:
  - `L1-Bmr001_first360-002` Bmr001_first360: The group decided to postpone the 'read numbers task' to first conduct a microphone identification check.
  - `L1-Bmr007_first360-004` Bmr007_first360: The meeting agenda was set to include: 1) Jane discussing research issues, 2) Adam discussing short research issues, and 3) a review of the list of accomplishments for IBM.
  - `L1-Bmr007_first360-006` Bmr007_first360: There are unresolved research issues, some carried over from the previous meeting, that are on the agenda for discussion.
  - `L1-Bmr007_first360-007` Bmr007_first360: me013 will participate in a conference call about a potential proposal and will update the group the following week if there are any developments.

### icsi-q006: What concrete evidence do the ICSI BMR meetings contain about annotation tool?
- expected L2 labels: annotation tool
- representative L1:
  - `L1-Bmr010_first360-038` Bmr010_first360: The team plans to modify the 'Transcriber' tool for checking transcripts. To address performance issues, the new design will display only the mixed waveform while still providing a user interface to edit different channe
  - `L1-Bmr010_first360-040` Bmr010_first360: The team needs to decide on the design for modifying the 'Transcriber' tool to support checking and augmenting transcripts. Key unresolved design points include how to handle multi-channel audio display (e.g., showing on
  - `L1-Bmr011_first360-029` Bmr011_first360: The 'multi-trans' software is being modified to handle multi-channel recording, which will enable precise time-stamping of the start and end of overlapping speech segments, a capability the original software lacked.
  - `L1-Bmr011_first360-031` Bmr011_first360: The team is awaiting the completion of modifications to the 'multi-trans' software, which are necessary to enable precise time-stamping of the start and end of overlapping speech segments. A prototype is complete but has

### icsi-q007: What did the ICSI BMR meetings discuss about data collection protocol?
- expected L2 labels: data collection protocol
- representative L1:
  - `L1-Bmr001_first360-008` Bmr001_first360: A data collection protocol was established requiring participants to write metadata on a form rather than speaking it. This is to ensure transcribers can later identify speakers. The process was refined to allow this wri
  - `L1-Bmr001_first360-011` Bmr001_first360: The written metadata on the recording forms, including speaker, gender, and microphone details, is necessary for transcribers to later identify who said what.
  - `L1-Bmr001_first360-013` Bmr001_first360: An argument was made to speak the metadata instead of writing it to avoid spending recording time on writing and maximize the time spent talking.
  - `L1-Bmr002_first360-005` Bmr002_first360: The data collection protocol was updated to allow participants to adjust their headset microphones for comfort, accepting the risk of potential audio level variations.

### icsi-q008: ICSI BMR meetings discussed annotation protocol. How did that topic evolve across meetings?
- expected L2 labels: annotation protocol
- representative L1:
  - `L1-Bmr013_first360-051` Bmr013_first360: The team adopted the approach of consulting with expert John Ohala for guidance on selecting which acoustic features to annotate.
  - `L1-Bmr014_first360-041` Bmr014_first360: A new transcription protocol was adopted for cleaning data, which includes conventions for numbers and acronyms. For numbers, a gloss is added to the transcription to clarify how they were spoken (e.g., 'ninety-two' vs.
  - `L1-Bmr015_first360-009` Bmr015_first360: The established transcription protocol for self-corrected reading errors (false starts) was to extract only the final, correct string.
  - `L1-Bmr015_first360-010` Bmr015_first360: The collected data contains uncorrected reading errors, where a speaker reads the wrong string at an individual string level and does not notice or correct the mistake.

### icsi-q009: What concrete evidence do the ICSI BMR meetings contain about digit reading task?
- expected L2 labels: digit reading task
- representative L1:
  - `L1-Bmr001_first360-015` Bmr001_first360: It is unclear whether participants are expected to explicitly label their own errors (e.g., 'mistake, disfluency, scratch') during the digit reading task, as was observed, or if this was an unprompted action.
  - `L1-Bmr002_first360-021` Bmr002_first360: The protocol for the digit reading task allows speakers to choose their own intonation, but suggests they read the numbers as if reciting a phone number.
  - `L1-Bmr002_first360-024` Bmr002_first360: There is an unresolved question regarding the data collection protocol for digit reading tasks. A participant noted that a slower, more natural pace for dictating a phone number would be easier for a machine to process,
  - `L1-Bmr005_first360-004` Bmr005_first360: The protocol for the reading task requires the speaker to first state the transcript number, then read each line, pausing briefly after each one.

### icsi-q010: What did the ICSI BMR meetings discuss about asr performance?
- expected L2 labels: asr performance
- representative L1:
  - `L1-Bmr012_first360-022` Bmr012_first360: The ASR evaluation process was corrected to fix a 'synch time problem' that caused an 80% error rate and truncated scoring. This bug resulted in misalignments between the reference and recognized text. The fix enables th
  - `L1-Bmr012_first360-023` Bmr012_first360: An ASR alignment and scoring bug, attributed to a 'synch time problem', is causing a high error rate (80%) and truncated scoring output. The misalignment between reference and recognized text is inconsistent, sometimes o
  - `L1-Bmr013_first360-004` Bmr013_first360: A long-term project goal was established to improve the speech recognizer's performance on distant microphone data over the next one to two years, targeting an improvement of one to two percent.
  - `L1-Bmr013_first360-006` Bmr013_first360: A key research challenge is the expected poor performance of the speech recognizer on distant microphone data from the newly collected digits corpus, with a long-term goal to improve this performance over the next one to

### icsi-q011: ICSI BMR meetings discussed data handling. How did that topic evolve across meetings?
- expected L2 labels: data handling
- representative L1:
  - `L1-Bmr007_first360-032` Bmr007_first360: The project will anonymize the data and results, in line with human subjects guidelines, to focus the analysis on general tendencies and speaker styles rather than individual performance.
  - `L1-Bmr007_first360-033` Bmr007_first360: The data should be anonymized to avoid singling out individuals, which aligns with human subjects research principles. The focus of the analysis is on general tendencies and different speaker styles, not on individual pe
  - `L1-Bmr008_first360-008` Bmr008_first360: To streamline data collection, the project is replacing per-session 'digits forms' with a single, unified speaker form that is filled out once per participant. In subsequent sessions, a speaker's information will be look
  - `L1-Bmr008_first360-012` Bmr008_first360: The current 'digits forms' are inefficient, becoming crowded with speaker-specific information that must be re-entered for each session.

### icsi-q012: What concrete evidence do the ICSI BMR meetings contain about project management?
- expected L2 labels: project management
- representative L1:
  - `L1-Bmr001_first360-027` Bmr001_first360: The team has decided to prioritize getting the recording setup into a good working state as quickly as possible.
  - `L1-Bmr010_first360-034` Bmr010_first360: The team concluded that the transcription task is now secured and will be completed, following the news that Brian has taken over the work.
  - `L1-Bmr010_first360-035` Bmr010_first360: Brian will check the output of the first transcription his team produces.
  - `L1-Bmr014_first360-013` Bmr014_first360: To better fulfill a stakeholder's information request, it was proposed that the team ask him to specify the particular topics he is interested in.
