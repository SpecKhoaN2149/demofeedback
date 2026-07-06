# Requirements Document

## Introduction

The NLP Feedback Processing feature transforms raw, unstructured customer feedback (emails, surveys, call transcripts, and social media posts) into structured, actionable insights for a telecom/connectivity company. It uses the Gemini API to perform theme classification, sentiment analysis, severity scoring, clustering of similar feedback, and prioritization.

This feature owns only the NLP processing layer of the broader Customer Feedback and Support Intake system. It accepts normalized feedback records as input and produces structured insight records as output, which downstream teams consume to surface high-impact problems quickly. Accuracy and output quality are the primary objectives.

The feature is designed as a processing pipeline: ingestion and normalization, NLP enrichment (classification, sentiment, severity) via Gemini, clustering of related feedback, and prioritization scoring. Because Gemini responses are exchanged as structured text (JSON), parsing and serialization correctness are treated as first-class requirements.

In addition to theme, sentiment, and severity, the feature enriches each feedback item with a Driver dimension (the entity responsible for or source of the issue) and an optional free-text Root_Cause description, both derived from real corporate escalation data. Feedback records may also carry optional regional/market metadata to support regional concentration analysis, and survey feedback may carry an optional Net Promoter Score (NPS). These additional dimensions are surfaced on insight, cluster, and batch output so downstream teams can analyze responsibility, root cause, and regional patterns.

## Glossary

- **NLP_Processor**: The overall system that converts raw customer feedback into structured insights.
- **Ingestion_Component**: The subsystem that accepts raw feedback items and produces normalized Feedback_Records.
- **Feedback_Record**: A normalized representation of a single customer feedback item, containing an identifier, source channel, cleaned text, and original metadata.
- **Raw_Feedback**: An unprocessed customer feedback item from a source channel (email, survey, call transcript, social post).
- **Source_Channel**: The origin of a feedback item; one of `email`, `survey`, `call_transcript`, or `social_post`.
- **Gemini_Client**: The subsystem that sends prompts to the Gemini API and receives responses.
- **Gemini_API**: The external Google Gemini large language model service used for NLP enrichment.
- **Classifier**: The subsystem that assigns one or more Theme labels to a Feedback_Record using the Gemini_Client.
- **Theme**: A category label describing the subject of feedback; one of a configurable set whose default members are `billing`, `network_speed`, `outage`, `support_experience`, `device_hardware`, `pricing`, `voluntary_disconnect`, `field_maintenance`, `move_transfer`, `account_management`, and `other`.
- **Sentiment_Analyzer**: The subsystem that assigns a Sentiment value to a Feedback_Record.
- **Sentiment**: A polarity label; one of `positive`, `neutral`, or `negative`, with an associated confidence score between 0.0 and 1.0.
- **Severity_Scorer**: The subsystem that assigns a Severity_Score to a Feedback_Record.
- **Severity_Score**: An integer from 1 to 5 indicating the operational impact of the feedback, where 5 is the most severe.
- **Clustering_Component**: The subsystem that groups semantically similar Feedback_Records into Clusters.
- **Cluster**: A group of Feedback_Records judged to describe the same underlying issue, with a representative label.
- **Prioritization_Component**: The subsystem that computes a Priority_Score for each Cluster.
- **Priority_Score**: A numeric value used to rank Clusters by importance, derived from severity, volume, and sentiment.
- **Insight_Record**: The structured output for a single Feedback_Record, containing its Themes, Sentiment, Severity_Score, Driver, Root_Cause, Region, NPS_Score, and Cluster assignment.
- **Driver_Classifier**: The subsystem that assigns exactly one Driver value to a Feedback_Record using the Gemini_Client.
- **Driver**: A classification label identifying the entity responsible for or the source of the feedback issue; one of a configurable set whose default members are `employee_driven`, `customer_driven`, `system_technology`, `business_rule_dispute`, `process_gap`, and `other`, with an associated confidence score between 0.0 and 1.0.
- **Root_Cause**: An optional, model-derived free-text description of the underlying cause of a feedback issue (for example, "Investigation Found No Issues", "Spectrum External Infrastructure Faulty", "Employee Failure - Did not follow process"); when present it is 1 to 500 characters in length.
- **Region**: An optional identifier of the geographic region or market associated with a Feedback_Record (for example, New York City, Midwest, Southeast, West, Northeast, Great Lakes, Mid-South, Northwest, Texas-Louisiana).
- **NPS_Score**: An optional Net Promoter Score captured from survey feedback in response to the question "How likely are you to recommend Spectrum to a friend or family member?"; an integer in the inclusive range 0 to 10.
- **Response_Parser**: The subsystem that parses Gemini_API JSON responses into internal data objects.
- **Response_Serializer**: The subsystem that serializes internal data objects into JSON for storage or downstream consumption.
- **API_Key**: The Gemini API credential supplied by the operator through configuration.
- **Operator**: The internal user who configures and runs the NLP_Processor.

## Requirements

### Requirement 1: Feedback Ingestion and Normalization

**User Story:** As an operator, I want raw feedback from multiple channels normalized into a common structure, so that downstream NLP steps process every item consistently.

#### Acceptance Criteria

1. WHEN a Raw_Feedback item is submitted, THE Ingestion_Component SHALL produce a Feedback_Record containing an identifier that is unique across all Feedback_Records produced by the Ingestion_Component, the Source_Channel, the cleaned text, and the original metadata unchanged from the Raw_Feedback item.
2. WHEN a Raw_Feedback item contains leading or trailing whitespace characters (space, tab, carriage return, or newline), THE Ingestion_Component SHALL remove only the leading and trailing whitespace from the cleaned text while preserving all characters between the first and last non-whitespace character.
3. IF a submitted Raw_Feedback item has text that is empty or whitespace-only before any processing, THEN THE Ingestion_Component SHALL reject that submitted item, produce no Feedback_Record for it, and record a validation error identifying the item by its assigned identifier.
4. IF a submitted Raw_Feedback item specifies a Source_Channel outside the defined set (email, survey, call_transcript, social_post), THEN THE Ingestion_Component SHALL reject that submitted item, produce no Feedback_Record for it, and record a validation error identifying the item by its assigned identifier.
5. WHEN a batch of up to 1,000 Raw_Feedback items is submitted, THE Ingestion_Component SHALL assign to every item in the batch, including rejected items, an identifier that is unique across all Feedback_Records produced by the Ingestion_Component.
6. IF a submitted batch contains more than 1,000 Raw_Feedback items, THEN THE Ingestion_Component SHALL reject the batch, process no items in it, and record a validation error indicating the batch size limit of 1,000 items was exceeded.
7. IF a Raw_Feedback item has cleaned text exceeding 10,000 characters after leading and trailing whitespace removal, THEN THE Ingestion_Component SHALL reject the item, produce no Feedback_Record for it, and record a validation error identifying the item by its assigned identifier.
8. WHERE a Raw_Feedback item supplies a region or market identifier in its metadata, THE Ingestion_Component SHALL store that identifier as the Region on the produced Feedback_Record.
9. IF a Raw_Feedback item supplies no region or market identifier in its metadata, THEN THE Ingestion_Component SHALL produce the Feedback_Record with the Region absent and SHALL NOT reject the item on the basis of the missing Region.
10. WHERE a Raw_Feedback item has a Source_Channel of `survey` and supplies an NPS_Score in its metadata, THE Ingestion_Component SHALL store the NPS_Score on the produced Feedback_Record as an integer in the inclusive range 0 to 10.
11. IF a Raw_Feedback item with a Source_Channel of `survey` supplies an NPS_Score that is non-integer or outside the inclusive range 0 to 10, THEN THE Ingestion_Component SHALL reject the item, produce no Feedback_Record for it, and record a validation error identifying the item by its assigned identifier.
12. WHENEVER the produced Feedback_Record has no NPS_Score present, including when the Raw_Feedback item supplies no NPS_Score in its metadata, THE Ingestion_Component SHALL produce the Feedback_Record with the NPS_Score absent and SHALL NOT reject the item on the basis of the absent NPS_Score.

### Requirement 2: Gemini API Configuration and Connectivity

**User Story:** As an operator, I want to configure the Gemini API credential and model, so that the NLP_Processor can call the Gemini service.

#### Acceptance Criteria

1. WHERE an API_Key is provided through configuration, THE Gemini_Client SHALL attach the API_Key as the authentication credential on every request it sends to the Gemini_API.
2. IF the API_Key is absent, empty, or whitespace-only at startup, THEN THE NLP_Processor SHALL stop initialization before any Feedback_Record is processed and report a configuration error identifying the missing API_Key.
3. WHEN the Gemini_Client initializes, THE Gemini_Client SHALL read the target Gemini model name from configuration and use that model name on every request it sends to the Gemini_API.
4. IF the Gemini model name is absent, empty, or whitespace-only at startup, THEN THE NLP_Processor SHALL stop initialization before any Feedback_Record is processed and report a configuration error identifying the missing model name.
5. IF the Gemini_API returns an authentication error, THEN THE Gemini_Client SHALL report an authentication failure and SHALL NOT send any retry request for that request, AND THE NLP_Processor SHALL fail the current operation.
6. THE NLP_Processor SHALL exclude the API_Key value from all log output and from all reported error messages.
7. THE NLP_Processor SHALL block all Feedback_Record processing until initialization completes successfully with a valid API_Key and a valid Gemini model name.

### Requirement 3: Gemini Request Resilience

**User Story:** As an operator, I want the system to handle transient Gemini API failures, so that processing remains reliable under intermittent errors.

#### Acceptance Criteria

1. IF the Gemini_API returns a rate-limit response, THEN THE Gemini_Client SHALL retry the request using exponential backoff with an initial delay of 1 second that doubles after each attempt up to a maximum delay of 60 seconds per attempt, for a configurable maximum number of attempts defaulting to 5 within the range 1 to 10.
2. IF the Gemini_API returns a transient server error or a network connection failure, THEN THE Gemini_Client SHALL retry the request using the same exponential backoff and maximum-attempt limit defined for rate-limit responses.
3. IF a Gemini_API request exceeds the configured request timeout, defaulting to 30 seconds within the range 1 to 120 seconds, THEN THE Gemini_Client SHALL abort the request, discard any partial response, and record a timeout error that identifies the associated Feedback_Record.
4. IF all retry attempts for a request fail, THEN THE Gemini_Client SHALL record a failure result for the associated Feedback_Record with an error indication describing the failure cause, and SHALL continue processing the remaining Feedback_Record items without aborting the batch.
5. WHEN the Gemini_Client retries a request, THE Gemini_Client SHALL resend the original request content unchanged.
6. IF a Gemini_API request fails for any reason, whether or not a retry was attempted, THEN THE Gemini_Client SHALL record a failure result for the associated Feedback_Record with an error indication describing the failure cause.
7. IF recording a timeout error for a Feedback_Record itself fails, THEN THE Gemini_Client SHALL log the timeout to an alternative log destination and SHALL continue processing the remaining Feedback_Record items without aborting the batch.

### Requirement 4: Gemini Response Parsing and Serialization

**User Story:** As an operator, I want Gemini responses parsed reliably and insights serialized to a stable format, so that enrichment results are accurate and durable.

#### Acceptance Criteria

1. WHEN the Gemini_API returns a JSON response in which all required fields are present and each field conforms to its schema-defined type and range, THE Response_Parser SHALL parse the response into the corresponding internal data object, mapping each schema field to its corresponding object field.
2. IF a Gemini_API response is not valid JSON, OR omits a required field, OR contains a field whose type or value range violates the expected schema, THEN THE Response_Parser SHALL record a parse error identifying the associated Feedback_Record, and SHALL NOT write any field of, or produce a partial, Insight_Record.
3. WHEN an Insight_Record satisfies the published output schema, THE Response_Serializer SHALL serialize the Insight_Record into JSON conforming to the published output schema.
4. IF an Insight_Record to be serialized is invalid or incomplete with respect to the published output schema, THEN THE Response_Serializer SHALL record a serialization error identifying the associated Feedback_Record and SHALL NOT produce output for that Insight_Record.
5. FOR ALL valid Insight_Records, serializing an Insight_Record and then parsing the serialized JSON SHALL produce an Insight_Record whose Themes and Theme confidence scores, Sentiment and Sentiment confidence score, Severity_Score, Driver and Driver confidence score, Root_Cause, Region, NPS_Score, and Cluster assignment are equal to those of the original (round-trip property).
6. FOR ALL valid expected-schema JSON values, parsing the JSON and then serializing the result SHALL produce JSON equal to the original normalized JSON, where normalized JSON has keys in lexicographic order and insignificant whitespace removed, and equality is byte-for-byte after normalization (round-trip property).

### Requirement 5: Theme Classification

**User Story:** As an internal analyst, I want each feedback item classified into themes, so that I can understand what subjects customers are raising.

#### Acceptance Criteria

1. WHEN a Feedback_Record is submitted to the Classifier, THE Classifier SHALL assign at least one Theme from the configured Theme set to the Feedback_Record.
2. THE Classifier SHALL assign each Theme value only from the configured Theme set, whose default members are (billing, network_speed, outage, support_experience, device_hardware, pricing, voluntary_disconnect, field_maintenance, move_transfer, account_management, other).
3. THE Classifier SHALL read the active Theme set from configuration at startup, such that an Operator can add or remove Theme members without modifying the Classifier implementation.
4. WHEN the Classifier assigns a Theme, THE Classifier SHALL attach a confidence score in the inclusive range 0.0 to 1.0 to that assigned Theme.
5. WHERE one or more Themes have a confidence score of at least 0.5, THE Classifier SHALL assign all such Themes from the configured Theme set to the Feedback_Record.
6. IF the Gemini_API output indicates no configured Theme applies, OR no candidate Theme has a confidence score of at least 0.5, THEN THE Classifier SHALL assign the Theme `other` to the Feedback_Record.
7. IF the Gemini_API returns a Theme value that is not in the configured Theme set, THEN THE Classifier SHALL discard that value and assign the Theme `other` to the Feedback_Record.
8. IF the Gemini_API is unavailable, OR a Gemini_API request for the Feedback_Record times out for any reason regardless of the elapsed duration, OR the Gemini_API does not return output within 30 seconds, THEN THE Classifier SHALL leave the Feedback_Record unclassified, preserve the original Feedback_Record without modification, and attach an error indication identifying the classification failure.
9. IF one or more Themes have a confidence score of at least 0.5 but the NLP_Processor fails to assign those Themes to the Feedback_Record, THEN THE NLP_Processor SHALL mark the Feedback_Record as failed and record a failure entry identifying the Feedback_Record.

### Requirement 6: Sentiment Analysis

**User Story:** As an internal analyst, I want sentiment assigned to each feedback item, so that I can gauge customer satisfaction.

#### Acceptance Criteria

1. WHEN a Feedback_Record is submitted to the Sentiment_Analyzer, THE Sentiment_Analyzer SHALL assign exactly one Sentiment value from the set (positive, neutral, negative).
2. WHEN the Sentiment_Analyzer assigns a Sentiment, THE Sentiment_Analyzer SHALL attach a confidence score in the inclusive range 0.0 to 1.0.
3. WHEN the Sentiment_Analyzer assigns a Sentiment, THE Sentiment_Analyzer SHALL record both the Sentiment value and its confidence score on the Insight_Record for the Feedback_Record regardless of the confidence score.
4. IF any condition prevents the Sentiment_Analyzer from assigning a Sentiment value from the Gemini_API output, including a timeout, a malformed response, or an omitted value, THEN THE Sentiment_Analyzer SHALL assign a default Sentiment of `neutral` and record a missing-sentiment note on the Insight_Record identifying the affected Feedback_Record.
5. IF the Sentiment_Analyzer produces a Sentiment value outside the set (positive, neutral, negative) or a confidence score outside the inclusive range 0.0 to 1.0, THEN THE NLP_Processor SHALL reject the Feedback_Record, retain the rejected Feedback_Record without producing an Insight_Record, and record a sentiment-validation error identifying the Feedback_Record, even when a timeout or other failure condition also applies to the same response.

### Requirement 7: Severity Scoring

**User Story:** As an internal analyst, I want each feedback item scored for severity, so that high-impact issues are distinguishable from minor ones.

#### Acceptance Criteria

1. WHEN the Severity_Scorer receives a Feedback_Record, THE Severity_Scorer SHALL assign exactly one Severity_Score that is an integer from 1 to 5 inclusive.
2. WHEN the Severity_Scorer assigns a Severity_Score, THE Severity_Scorer SHALL record on the Insight_Record at least one contributing factor for that Severity_Score, where each factor is a text entry of 1 to 500 characters.
3. IF the Gemini_API output completely omits a severity value (a missing severity) and provides no severity value that violates the integer 1-to-5 range, THEN THE Severity_Scorer SHALL process the Feedback_Record with a default Severity_Score of 1 and record a missing-severity note on the Insight_Record identifying the affected Feedback_Record.
4. IF the Gemini_API output provides a severity value that is non-integer or outside the range of 1 to 5 inclusive (an invalid severity), THEN THE NLP_Processor SHALL reject the Feedback_Record, retain the rejected Feedback_Record without producing an Insight_Record, and record a severity-range error identifying the Feedback_Record, AND THE Severity_Scorer SHALL evaluate invalid severity before missing severity such that a response that is simultaneously interpretable as missing and invalid is treated as invalid severity.
5. IF the Gemini_API does not return a response within 30 seconds of the Severity_Scorer requesting a severity value, AND the response is neither a missing severity nor an invalid severity, THEN THE Severity_Scorer SHALL assign a default Severity_Score of 1 and record a severity-unavailable note on the Insight_Record identifying the affected Feedback_Record.

### Requirement 8: Clustering of Similar Feedback

**User Story:** As an internal analyst, I want similar feedback grouped together, so that I can see the volume behind each issue.

#### Acceptance Criteria

1. WHEN a set of one or more Feedback_Records is processed, THE Clustering_Component SHALL assign each Feedback_Record to exactly one Cluster, such that the Clusters are mutually exclusive.
2. WHEN the Clustering_Component creates a Cluster, THE Clustering_Component SHALL produce a non-empty representative label of at most 120 characters derived from the text of the Feedback_Records assigned to that Cluster.
3. WHEN two Feedback_Records have a semantic similarity that strictly exceeds the configurable similarity threshold, THE Clustering_Component SHALL assign both Feedback_Records to the same Cluster.
4. THE Clustering_Component SHALL include every input Feedback_Record in exactly one Cluster of the output, such that the total count of clustered Feedback_Records equals the count of input Feedback_Records.
5. IF the semantic similarity between a Feedback_Record and every other Feedback_Record in the input set does not strictly exceed the configurable similarity threshold, THEN THE Clustering_Component SHALL assign that Feedback_Record to a Cluster containing only that Feedback_Record.
6. WHEN the input set of Feedback_Records is empty, THE Clustering_Component SHALL produce zero Clusters and SHALL produce the clustering output.
7. WHERE the Clustering_Component completes an initial Cluster assignment, THE Clustering_Component MAY merge in a post-processing step any Clusters containing similar Feedback_Records, provided that after merging every pair of Feedback_Records whose semantic similarity strictly exceeds the configurable similarity threshold remains assigned to the same Cluster.

### Requirement 9: Prioritization

**User Story:** As an internal team lead, I want clusters ranked by priority, so that my team addresses the most important problems first.

#### Acceptance Criteria

1. WHEN clustering completes, THE Prioritization_Component SHALL compute for each Cluster a non-negative Priority_Score derived deterministically from the Severity_Scores, the count of Feedback_Records, and the Sentiment values within the Cluster, such that identical inputs always yield an identical Priority_Score.
2. WHEN one or more Clusters exist, THE Prioritization_Component SHALL order the Clusters in descending Priority_Score.
3. WHERE two Clusters have equal Priority_Scores, THE Prioritization_Component SHALL order the Cluster with the higher Feedback_Record count first, and WHERE the Feedback_Record counts are also equal, THE Prioritization_Component SHALL order the Clusters by ascending Cluster label, AND THE Prioritization_Component SHALL permit two Clusters to carry identical labels, in which case it SHALL preserve their existing relative order deterministically.
4. THE Prioritization_Component SHALL constrain each Priority_Score to a minimum of zero, such that no Priority_Score is negative.
5. THE Prioritization_Component SHALL record the Priority_Score on each Cluster in the output.
6. WHERE two Clusters are identical except that one has a strictly higher total of Severity_Scores, THE Prioritization_Component SHALL assign that Cluster a Priority_Score greater than or equal to the other.
7. WHERE two Clusters are identical except that one has a strictly higher count of Feedback_Records, THE Prioritization_Component SHALL assign that Cluster a Priority_Score greater than or equal to the other.
8. WHERE two Clusters are identical except that one has a strictly higher count of negative Sentiment values, THE Prioritization_Component SHALL assign that Cluster a Priority_Score greater than or equal to the other.
9. WHERE a per-region subscriber or population base is provided in configuration, THE Prioritization_Component MAY additionally compute for each Cluster a normalized priority index equal to the Cluster's Feedback_Record volume divided by the configured subscriber base for the Cluster's predominant Region and scaled to a per-1,000,000-subscriber basis, and SHALL record the normalized priority index on the Cluster as an additional field.
10. IF no per-region subscriber or population base is provided in configuration, THEN THE Prioritization_Component SHALL compute no normalized priority index and SHALL retain the Priority_Score, ordering, and tie-breaking behavior defined in this requirement unchanged.
11. THE Prioritization_Component SHALL derive the Priority_Score, Cluster ordering, and tie-breaking solely from Severity_Scores, Feedback_Record counts, and Sentiment values, such that the presence or absence of a configured per-region subscriber base does not alter the Priority_Score, the Cluster ordering, or the tie-breaking outcome.

### Requirement 10: Batch Processing and Output Assembly

**User Story:** As an operator, I want to process a batch of feedback and receive a complete structured result, so that downstream teams can consume the insights.

#### Acceptance Criteria

1. WHEN a batch of 1 to 10,000 Feedback_Records is submitted, THE NLP_Processor SHALL produce one Insight_Record for each successfully processed Feedback_Record, where a Feedback_Record is successfully processed when classification, sentiment analysis, severity scoring, and cluster assignment all complete without error, and SHALL produce the Insight_Records output even when the count of successful Insight_Records is zero.
2. IF processing of an individual Feedback_Record fails at any enrichment stage, THEN THE NLP_Processor SHALL exclude that Feedback_Record from the Insight_Records and record a failure entry containing the Feedback_Record identifier and a reason.
3. WHEN a batch completes, THE NLP_Processor SHALL produce a summary reporting the count of submitted records, the count of successful Insight_Records, and the count of failures, such that the count of successful Insight_Records plus the count of failures equals the count of submitted records.
4. WHEN a batch completes, THE NLP_Processor SHALL emit the assembled output as JSON conforming to the published output schema.
5. IF a submitted batch is empty or contains more than 10,000 Feedback_Records, THEN THE NLP_Processor SHALL produce no Insight_Records and record a batch-validation error indicating the violated batch size bound.

### Requirement 11: Accuracy and Quality Controls

**User Story:** As an operator, I want measures that maximize NLP accuracy, so that the insights are trustworthy.

#### Acceptance Criteria

1. THE Gemini_Client SHALL instruct the Gemini_API to return output in the defined JSON schema for each enrichment request.
2. WHEN the Gemini_API returns a confidence score below the configured review threshold (a value between 0.0 and 1.0 inclusive, defaulting to 0.70) for a Theme or Sentiment, THE NLP_Processor SHALL set a review flag on the affected Insight_Record.
3. IF the NLP_Processor detects a confidence score below the configured review threshold but fails to set the review flag on the affected Insight_Record, THEN THE NLP_Processor SHALL record a system error identifying the affected Insight_Record, and SHALL retain the affected Insight_Record without applying the flag.
4. THE NLP_Processor SHALL record on each Insight_Record the Gemini model name used to produce the result.
5. WHERE a ground-truth labeled dataset of one or more labeled Feedback_Records is provided, THE NLP_Processor SHALL compute classification accuracy as the proportion of evaluated Feedback_Records whose assigned Themes exactly match the dataset's labeled Themes, expressed as a value between 0.0 and 1.0 inclusive.
6. WHERE a ground-truth labeled dataset is provided, THE NLP_Processor SHALL report the computed classification accuracy value in the batch output.
7. WHERE no ground-truth labeled dataset is provided, THE NLP_Processor SHALL omit the classification accuracy value from the batch output and SHALL NOT report a default classification accuracy value.

### Requirement 12: Driver Classification

**User Story:** As an internal analyst, I want each feedback item classified by the entity responsible for the issue, so that I can distinguish employee-driven, customer-driven, system, and process-related drivers.

#### Acceptance Criteria

1. WHEN a Feedback_Record is submitted to the Driver_Classifier, THE Driver_Classifier SHALL assign exactly one Driver value from the configured Driver set to the Feedback_Record.
2. THE Driver_Classifier SHALL assign each Driver value only from the configured Driver set, whose default members are (employee_driven, customer_driven, system_technology, business_rule_dispute, process_gap, other).
3. THE Driver_Classifier SHALL read the active Driver set from configuration at startup, such that an Operator can add or remove Driver members without modifying the Driver_Classifier implementation.
4. WHEN the Driver_Classifier assigns a Driver, THE Driver_Classifier SHALL attach a confidence score in the inclusive range 0.0 to 1.0 and SHALL record both the Driver value and its confidence score on the Insight_Record for the Feedback_Record.
5. IF the Gemini_API output omits a Driver value, OR indicates no configured Driver applies, OR returns a Driver value that exists but is not in the configured Driver set, THEN THE Driver_Classifier SHALL treat the case as no configured Driver applying, assign the Driver `other` to the Feedback_Record, and record a missing-driver note on the Insight_Record identifying the affected Feedback_Record.
6. IF the Gemini_API returns a Driver value that is not in the configured Driver set, THEN THE Driver_Classifier SHALL discard that value, assign the Driver `other` to the Feedback_Record, and record a missing-driver note on the Insight_Record identifying the affected Feedback_Record.
7. IF the Driver_Classifier produces a Driver confidence score outside the inclusive range 0.0 to 1.0, THEN THE NLP_Processor SHALL reject the Feedback_Record, retain the rejected Feedback_Record without producing an Insight_Record, and record a driver-validation error identifying the Feedback_Record.

### Requirement 13: Root Cause Capture

**User Story:** As an internal analyst, I want a free-text root cause captured for each feedback item when available, so that I can understand the underlying reason behind an issue.

#### Acceptance Criteria

1. WHERE the Gemini_API output provides a Root_Cause description for a Feedback_Record, THE NLP_Processor SHALL record the Root_Cause on the Insight_Record as a text value of 1 to 500 characters.
2. IF the Gemini_API output provides a Root_Cause description longer than 500 characters, THEN THE NLP_Processor SHALL reject the Feedback_Record, retain the rejected Feedback_Record without producing an Insight_Record, and record both a missing-root-cause note and a root-cause-length error identifying the Feedback_Record.
3. IF the Gemini_API output omits a Root_Cause description, THEN THE NLP_Processor SHALL produce the Insight_Record with the Root_Cause absent, record a missing-root-cause note on the Insight_Record identifying the affected Feedback_Record, and SHALL NOT fail the Feedback_Record on the basis of the missing Root_Cause.

### Requirement 14: Region and NPS Surfacing

**User Story:** As an internal analyst, I want regional and NPS metadata surfaced on insights, clusters, and batch output, so that I can analyze regional concentration and survey advocacy.

#### Acceptance Criteria

1. WHERE a Feedback_Record carries a Region, THE NLP_Processor SHALL record that Region on the Insight_Record produced for the Feedback_Record.
2. WHERE a Feedback_Record carries an NPS_Score, THE NLP_Processor SHALL record that NPS_Score on the Insight_Record produced for the Feedback_Record as an integer in the inclusive range 0 to 10, AND IF a carried NPS_Score is non-integer or outside the inclusive range 0 to 10, THEN THE NLP_Processor SHALL clamp it to the nearest bound of the inclusive range 0 to 10 and continue producing the Insight_Record rather than failing the Feedback_Record.
3. WHEN the Clustering_Component produces a Cluster, THE Clustering_Component SHALL record on the Cluster the set of distinct Region values present among the Feedback_Records assigned to that Cluster.
4. WHEN a batch completes, THE NLP_Processor SHALL surface in the batch output the Region of each Insight_Record for which a Region is present.
5. IF an Insight_Record has no Region present, THEN THE NLP_Processor SHALL produce that Insight_Record with the Region absent and SHALL NOT fail the Feedback_Record on the basis of the absent Region.

### Requirement 15: NPS Capture for Surveys

**User Story:** As an operator, I want NPS scores captured from survey feedback, so that survey advocacy can be measured alongside qualitative insights.

#### Acceptance Criteria

1. WHERE a survey Raw_Feedback item includes a Net Promoter Score in response to the question "How likely are you to recommend Spectrum to a friend or family member?", THE Ingestion_Component SHALL capture that score as the NPS_Score on the Feedback_Record metadata as an integer in the inclusive range 0 to 10.
2. THE Ingestion_Component SHALL capture an NPS_Score only for Feedback_Records whose Source_Channel is `survey`.
3. IF a Raw_Feedback item whose Source_Channel is not `survey` includes an NPS value, THEN THE Ingestion_Component SHALL produce the Feedback_Record with the NPS_Score absent and record a non-survey-nps note identifying the item by its assigned identifier.
4. IF a survey Raw_Feedback item includes an NPS value that is non-integer or outside the inclusive range 0 to 10, THEN THE Ingestion_Component SHALL reject the item, produce no Feedback_Record for it, and record a validation error identifying the item by its assigned identifier.
