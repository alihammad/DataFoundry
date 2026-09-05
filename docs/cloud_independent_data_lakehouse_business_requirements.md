# Cloud Independent Data Lakehouse Platform
## Business Requirements Document

**Document Version:** 1.0  
**Status:** Draft  
**Product:** Cloud Independent Data Lakehouse Platform  
**Target Clouds:** AWS and GCP  
**Primary Users:** Data Engineers, Analytics Engineers, Data Scientists, ML Engineers, Analysts, Application Developers, Platform Engineers

---

# 1. Executive Summary

The organisation requires a modern, cloud-independent data lakehouse platform that enables teams to rapidly provision, configure and operate enterprise-grade data platforms without building cloud-specific infrastructure and ingestion pipelines from scratch.

The platform will provide a **one-click deployment experience** whereby an authorised user selects a target cloud provider, supplies configuration parameters, selects required capabilities and data sources, and the platform automatically provisions the required infrastructure, storage, compute, ingestion, transformation, governance and consumption capabilities.

The platform will adopt the **Medallion Architecture**, consisting of:

**Bronze → Silver → Gold**

Data will initially be ingested from a variety of enterprise and external sources, including:

- Relational databases
- SQL Server
- PostgreSQL
- MySQL
- Oracle
- CSV
- JSON
- XML
- Text files
- Object storage
- APIs
- SaaS applications
- Event/streaming sources
- Other structured and semi-structured sources

The platform must abstract cloud-specific implementation details from users wherever practical.

For example:

> A user should not need to understand whether the underlying storage is GCS or S3 in order to create a lakehouse dataset.

Similarly, the platform should provide a common logical interface for compute, orchestration, ingestion, metadata, governance and observability while allowing the underlying implementation to differ between AWS and GCP.

---

# 2. Product Vision

## 2.1 Vision

Create a **self-service, cloud-independent data platform** that allows organisations to deploy a production-ready lakehouse and onboard new data sources in minutes rather than weeks.

---

# 3. Product Objectives

The platform should achieve the following objectives.

### O1. One-click platform deployment

Allow an authorised user to deploy a complete lakehouse environment with minimal manual intervention.

### O2. Cloud independence

Support AWS and GCP through a common platform abstraction.

The logical architecture should remain consistent even where underlying cloud services differ.

### O3. Self-service data ingestion

Enable users to configure data sources and ingestion pipelines without requiring engineers to write custom ingestion code for common use cases.

### O4. Standardised data architecture

Establish a common Medallion Architecture:

```text
                ┌────────────────────┐
                │    DATA SOURCES    │
                └─────────┬──────────┘
                          │
                          ▼
                ┌────────────────────┐
                │      BRONZE        │
                │ Raw / Immutable    │
                └─────────┬──────────┘
                          │
                    Transform
                          │
                          ▼
                ┌────────────────────┐
                │      SILVER        │
                │ Clean / Conformed  │
                └─────────┬──────────┘
                          │
                    Transform
                          │
                          ▼
                ┌────────────────────┐
                │       GOLD         │
                │ Business Ready     │
                └─────────┬──────────┘
                          │
          ┌───────────────┼────────────────┐
          ▼               ▼                ▼
     Semantic Layer   Data Warehouse      APIs
          │               │                │
          └───────────────┼────────────────┘
                          ▼
                ┌────────────────────┐
                │ DATA CONSUMERS     │
                │                    │
                │ AI / ML            │
                │ Data Science       │
                │ BI / Reporting     │
                │ Applications       │
                │ Analysts           │
                └────────────────────┘
```

### O5. Reduce engineering effort

Maximise reuse through standardised components, templates and managed services.

### O6. Make data discoverable

Provide cataloguing, metadata, lineage, ownership and data quality capabilities.

### O7. Make the platform AI-native

Use AI agents to automate repetitive engineering, operational and governance activities wherever this can be done safely and reliably.

---

# 4. Guiding Architectural Principles

## 4.1 Cloud agnostic by design

Cloud independence must exist at the **platform abstraction level**, not by pretending AWS and GCP services are identical.

The platform should define logical capabilities such as:

```text
Object Storage
Compute
Orchestration
Metadata
Catalog
Identity
Secrets
Monitoring
Streaming
Data Warehouse
API Gateway
```

Each cloud implementation maps these logical capabilities to appropriate services.

## 4.2 Quality before promotion

**No data should be promoted to the next lakehouse layer unless it has passed the quality, schema, security and contractual requirements defined for that layer.**

The platform shall favour early detection and prevention over downstream remediation. Invalid data should be quarantined, not propagated.

## 4.3 Portable core, cloud-specific implementations

The platform should not attempt to create a lowest-common-denominator abstraction that prevents teams from using valuable cloud-native capabilities.

The preferred approach is a **portable core with cloud-specific implementations where they provide meaningful value**.

```text
                    PLATFORM API
                         │
          ┌──────────────┼──────────────┐
          │              │              │
       Storage        Compute       Identity
          │              │              │
      ┌───┴───┐      ┌───┴───┐      ┌───┴───┐
      AWS     GCP     AWS     GCP     AWS    GCP
```

---

# 5. Target Cloud Architecture

The initial target clouds are:

- AWS
- GCP

The architecture should allow additional clouds to be introduced later without fundamentally redesigning the platform.

Potential future targets:

- Azure
- On-premises
- Private cloud
- Kubernetes

---

# 6. Technology Strategy

The platform should favour open standards and portable technologies.

| Capability | Preferred approach |
|---|---|
| IaC | Terraform |
| Storage | Cloud object storage |
| Table format | Apache Iceberg |
| Query engine | DuckDB + cloud-native engines |
| Ingestion | Airbyte + custom connectors |
| Transformation | dbt / SQL / Spark where required |
| Orchestration | Cloud-neutral orchestration abstraction |
| Metadata | Open metadata standards |
| Catalog | Pluggable |
| Data quality | Great Expectations / Soda / equivalent |
| APIs | Standard REST APIs |
| Semantic layer | Metric/semantic-layer abstraction |
| Containers | Docker |
| CI/CD | Git-based |
| Authentication | Cloud-native IAM + platform RBAC |
| Secrets | Cloud KMS / Secrets Manager equivalents |
| Observability | OpenTelemetry-compatible approach |
| AI | Agent framework + LLM abstraction |

These technologies should be evaluated rather than mandated prematurely.

---

# 7. One-Click Deployment

## 7.1 Requirement

The platform shall provide a mechanism for deploying a complete lakehouse environment using a single user-initiated deployment operation.

Example:

```text
Create Data Platform

Platform Name:
    Customer Analytics Platform

Cloud:
    ○ AWS
    ● GCP

Region:
    australia-southeast1

Environment:
    ○ Development
    ● Production

Capabilities:
    ☑ Lakehouse
    ☑ Ingestion
    ☑ Transformation
    ☑ Data Quality
    ☑ Catalog
    ☑ Semantic Layer
    ☑ API
    ☑ Monitoring
    ☑ AI Agents

[ Deploy Platform ]
```

The system should then:

1. Validate configuration
2. Generate deployment configuration
3. Generate Terraform configuration
4. Validate Terraform
5. Provision infrastructure
6. Configure platform services
7. Initialise metadata/catalog
8. Initialise storage zones
9. Configure networking
10. Configure IAM
11. Configure monitoring
12. Deploy ingestion services
13. Deploy orchestration
14. Run platform health checks
15. Present the platform as ready

---

# 8. Infrastructure as Code

Terraform shall be the primary infrastructure-as-code technology.

The platform should provide reusable Terraform modules for:

- Networking
- Object storage
- IAM
- Compute
- Databases
- Messaging
- Orchestration
- Monitoring
- Secrets
- API infrastructure
- Data platform components

The Terraform layer should be separated into:

```text
platform/
    core/
    networking/
    security/
    storage/
    compute/
    ingestion/
    orchestration/
    catalog/
    observability/
    api/
```

Cloud implementations should be isolated.

For example:

```text
terraform/
    aws/
        storage/
        compute/
        networking/

    gcp/
        storage/
        compute/
        networking/
```

The platform's logical configuration should remain cloud-independent.

---

# 9. Environment Management

The platform must support:

- Development
- Test
- UAT
- Production

Environment configuration should be declarative.

Example:

```yaml
environment:
  name: production
  cloud: gcp
  region: australia-southeast1

lakehouse:
  storage: object_storage
  table_format: iceberg

ingestion:
  enabled: true

catalog:
  enabled: true

semantic_layer:
  enabled: true
```

---

# 10. Data Ingestion

## 10.1 Objective

Provide a standardised ingestion framework capable of ingesting data from a broad range of sources.

### Databases

- SQL Server
- PostgreSQL
- MySQL
- Oracle
- Other JDBC/ODBC-compatible databases

### Files

- CSV
- JSON
- XML
- Parquet
- Avro
- Text
- Excel where appropriate

### APIs

- REST APIs
- GraphQL where required

### SaaS

Examples:

- Salesforce
- ServiceNow
- HubSpot
- Other enterprise SaaS platforms

### Streaming

Potential support for:

- Kafka
- Pub/Sub
- Kinesis
- Other event platforms

---

# 11. Airbyte Evaluation

The platform should **evaluate the use of Airbyte rather than automatically developing bespoke ingestion connectors**.

The evaluation should determine:

- Connector coverage
- Reliability
- Incremental ingestion
- CDC capabilities
- Schema evolution
- Authentication
- Performance
- Operational complexity
- Cost
- Cloud portability
- Extensibility
- Data residency
- Security
- Monitoring
- Failure recovery

The preferred approach should be:

```text
                 Ingestion Manager
                        │
              ┌─────────┴─────────┐
              │                   │
           Airbyte          Custom Connector
              │                   │
              └─────────┬─────────┘
                        ▼
                     Bronze
```

Custom ingestion code should only be developed where an existing connector does not adequately satisfy requirements.

---

# 12. Bronze Layer

The Bronze layer shall contain raw source data.

Characteristics:

- Immutable where practical
- Source-aligned
- Minimal transformation
- Replayable
- Auditable
- Schema-aware
- Partitioned appropriately
- Versioned where supported

Metadata should include:

- Source system
- Source table/file
- Ingestion timestamp
- Batch ID
- Pipeline ID
- Record count
- Source version
- Checksum where appropriate
- Ingestion status

Example:

```text
bronze/
    customer/
        source=crm/
            ingestion_date=2026-09-05/
```

---

# 13. Silver Layer

The Silver layer shall contain cleaned and conformed data.

Responsibilities include:

- Data cleansing
- Standardisation
- Type conversion
- Deduplication
- Schema enforcement
- Data quality validation
- Business-independent transformations
- Entity resolution where required
- Handling malformed records

Silver data should be suitable for direct analyst consumption.

---

# 14. Gold Layer

Gold represents business-ready datasets.

Examples:

```text
customer_360
sales_performance
customer_revenue
product_performance
claims_summary
marketing_performance
```

Gold datasets should:

- Have clear ownership
- Have documented definitions
- Have data quality rules
- Have business metadata
- Be version controlled
- Be discoverable through the catalog
- Be optimised for consumption

---

# 15. Table Format

The platform should evaluate **Apache Iceberg** as the standard lakehouse table format.

Requirements include:

- ACID transactions
- Schema evolution
- Partition evolution
- Time travel
- Versioning
- Concurrent writes
- Metadata management
- Engine interoperability

The table format should enable different compute engines to access the same underlying datasets.

---

# 16. DuckDB Evaluation

DuckDB should be evaluated as an important component of the platform, particularly for:

- Analyst workloads
- Local development
- Data exploration
- File-based querying
- Testing
- Lightweight transformations
- CI/CD data validation
- Data engineering development
- Small and medium datasets

A key requirement is that analysts should be able to query Silver and Gold datasets without necessarily loading the data into a traditional warehouse.

Example:

```sql
SELECT
    customer_id,
    SUM(revenue)
FROM silver.sales
GROUP BY customer_id;
```

DuckDB could potentially provide a lightweight query interface over lakehouse files.

The architecture should therefore avoid assuming that every analytical query must go through a cloud data warehouse.

---

# 17. Analyst Experience

Analysts should be able to:

- Browse datasets
- Search metadata
- Understand schemas
- Query Silver
- Query Gold
- Download results
- Create notebooks
- Save queries
- Share queries
- Explore data quality
- View lineage

Potential experience:

```text
Data Catalog
      │
      ▼
Customer Sales
      │
      ├── Schema
      ├── Quality
      ├── Lineage
      ├── Owner
      └── Query
             │
             ▼
          SQL Editor
             │
             ▼
           Results
```

---

# 18. Semantic Layer

The platform shall provide a semantic layer between physical data and downstream consumers.

The semantic layer should define:

- Business metrics
- Dimensions
- Measures
- Relationships
- Business definitions
- Access policies

Example:

```text
Revenue
    =
SUM(order.amount)

Customer
    =
customer_id

Active Customer
    =
customer with transaction in last 90 days
```

This prevents every downstream team from independently implementing business logic.

---

# 19. Data Warehouse Integration

The platform should support direct consumption through cloud warehouses.

For GCP this may include BigQuery.

For AWS this may include appropriate warehouse/query services.

The important requirement is that consumers should not need to understand the physical implementation of the lakehouse.

---

# 20. API Consumption

The platform shall support APIs for applications and products that need governed programmatic access to data.

Example:

```text
GET /customers/{customer_id}

GET /customers/{customer_id}/orders

GET /products/{product_id}/performance
```

API requirements:

- Authentication
- Authorisation
- Rate limiting
- Auditing
- Monitoring
- Versioning
- OpenAPI documentation
- Usage analytics

---

# 21. AI and ML Consumption

The platform must support AI/ML workloads as first-class consumers.

Capabilities should include:

- Feature datasets
- Training datasets
- Curated datasets
- Vector-ready data
- Metadata access
- Data quality information
- Data lineage
- Dataset discovery
- Embedding pipelines where appropriate
- Model-serving data access

AI/ML teams should be able to discover:

> "Which dataset contains reliable customer transaction data for the last three years?"

and understand:

- Where it came from
- How it was transformed
- Its quality
- Who owns it
- How frequently it is refreshed
- Whether it is suitable for ML

---

# 22. Data Governance

Governance must be built into the platform rather than implemented afterwards.

## Data ownership

Every dataset should have:

- Owner
- Steward
- Domain
- Description
- Criticality

## Classification

Data should support classifications such as:

```text
PUBLIC
INTERNAL
CONFIDENTIAL
RESTRICTED
```

## Sensitive data

The platform should support identification and handling of sensitive fields.

Examples:

- Personal information
- Financial information
- Credentials
- Confidential business information

## Access control

Support:

- Role-based access
- Dataset-level permissions
- Table-level permissions
- Column-level permissions
- Row-level permissions where required

---

# 23. Data Quality

Data quality should be treated as a platform capability.

The platform shall implement **shift-left data quality and automated testing at every stage of the data lifecycle**.

The fundamental principle shall be:

> **Data must pass the quality and contract checks for its current layer before it is promoted to the next layer.**

The platform must prevent invalid, incomplete, corrupted or structurally incompatible data from propagating downstream.

The intended flow is:

```text
Source
   │
   ▼
Ingestion Tests
   │
   │ PASS
   ▼
Bronze
   │
   ▼
Bronze Tests
   │
   │ PASS
   ▼
Silver Transformation
   │
   ▼
Silver Tests
   │
   │ PASS
   ▼
Gold Transformation
   │
   ▼
Gold Tests
   │
   │ PASS
   ▼
Semantic Layer
   │
   ▼
Consumers
```

If a test fails:

```text
                  TEST FAILED
                       │
                       ▼
                ┌─────────────┐
                │ STOP PROMOTE │
                └──────┬──────┘
                       │
             ┌─────────┴─────────┐
             ▼                   ▼
          Alert              Investigate
```

The failed data must not automatically propagate to the next layer.

---

# 23A. Testing Philosophy

Testing should be treated as a **data pipeline control mechanism**, rather than something performed after data has already reached consumers.

The platform should follow:

> **Detect as early as possible. Fail as early as necessary. Never knowingly promote bad data.**

This should apply to:

- Ingestion
- Bronze
- Silver
- Gold
- Semantic layer
- APIs
- Data warehouse
- AI/ML datasets

---

# 23B. Ingestion-Level Testing

Tests should begin **before or during ingestion** wherever possible.

### File validation

- File exists
- File is readable
- File is not corrupted
- Expected file format
- Expected encoding
- Expected delimiter
- Expected header
- File checksum

### File security

- File is encrypted where required
- File signature is valid
- File originated from an approved source

### Schema validation

```text
Expected:
customer_id INTEGER
name STRING
email STRING
created_date DATE
```

If the source sends:

```text
customer_id STRING
```

the ingestion pipeline should detect the incompatibility before promoting the data.

---

# 23C. Source Data Contracts

The platform should support **data contracts** between data producers and consumers.

A data contract may define:

```yaml
dataset: customer

schema:
  customer_id:
    type: integer
    nullable: false

  email:
    type: string
    nullable: false

  created_date:
    type: date
    nullable: false
```

The platform should validate incoming data against the contract.

Contract violations should be classified as:

- Breaking
- Non-breaking
- Warning

For example:

```text
New nullable column       → Warning
New non-nullable column   → Breaking
Column removed            → Breaking
INTEGER → STRING          → Breaking
```

---

# 23D. Bronze Layer Testing

Bronze should preserve the source data, but that does **not** mean it should be completely uncontrolled.

Tests should include:

- Record count
- File count
- Duplicate files
- File integrity
- Schema compatibility
- Nullability
- Data type validation
- Partition validation
- Duplicate records where detectable
- Source-to-Bronze reconciliation
- Ingestion completeness

For example:

```text
Source records:      1,000,000
Bronze records:        999,870

Difference:              130

Result:                  FAIL
```

The platform should prevent promotion to Silver until the issue is resolved or explicitly overridden according to policy.

---

# 23E. Silver Layer Testing

Silver represents **cleaned and conformed data**, so testing should become significantly more sophisticated.

Tests should include:

### Schema tests

- Correct data types
- Required columns
- Unexpected columns
- Schema evolution

### Completeness

```text
customer_id IS NOT NULL
```

### Uniqueness

```text
customer_id IS UNIQUE
```

### Validity

```text
email IS VALID
transaction_amount >= 0
```

### Referential integrity

```text
order.customer_id
    must exist in
customer.customer_id
```

### Business-independent integrity

Examples:

```text
start_date <= end_date

quantity >= 0

currency IS NOT NULL
```

---

# 23F. Gold Layer Testing

Gold datasets represent business-ready information and therefore require the strongest validation.

Testing should include:

### Business rules

```text
Revenue = Quantity × Unit Price
```

### Aggregation validation

```text
Gold Revenue ≈ Silver Revenue
```

subject to documented business transformations.

### Reconciliation

```text
Silver Transactions
        │
        ▼
Aggregation
        │
        ▼
Gold Revenue
```

The platform should validate that transformations have produced expected outcomes.

---

# 23G. Semantic Layer Testing

The semantic layer should also be tested.

For example:

```text
Metric:
Customer Revenue

Definition:
SUM(order_amount)
WHERE order_status = 'COMPLETED'
```

Tests should validate:

- Metric definitions
- Metric calculations
- Dimension relationships
- Aggregations
- Filter behaviour
- Data freshness
- Referential integrity

This prevents inconsistent definitions of metrics across reporting, AI and applications.

---

# 23H. API Testing

Where datasets are exposed through APIs, automated tests should validate:

- Schema
- Response structure
- Data types
- Authentication
- Authorisation
- Business rules
- Response completeness
- Performance
- Data freshness

---

# 23I. AI/ML Dataset Testing

AI/ML datasets should have additional validation.

Examples:

- Missing values
- Outliers
- Distribution changes
- Feature drift
- Label leakage
- Duplicate records
- Training/validation leakage
- Unexpected categorical values
- Sensitive information exposure

Example:

```text
Training Dataset
       │
       ▼
Data Quality Tests
       │
       ▼
Statistical Tests
       │
       ▼
PII Detection
       │
       ▼
ML Dataset Approved
```

---

# 23J. Test Categories

The platform should support multiple types of tests.

| Test Type | Example |
|---|---|
| Schema | Column exists |
| Type | INTEGER expected |
| Nullability | ID cannot be null |
| Uniqueness | Customer ID unique |
| Completeness | 99% records populated |
| Validity | Amount >= 0 |
| Referential | Customer exists |
| Reconciliation | Source = Bronze |
| Freshness | Data < 30 mins old |
| Volume | Record count within expected range |
| Distribution | Values within expected distribution |
| Business rule | Revenue calculation |
| Security | PII correctly protected |
| Contract | Source schema compatible |
| Transformation | Expected output |
| Statistical | Detect anomalies |

---

# 23K. Quality Gates

Every layer should have a configurable **quality gate**.

Example:

```text
                 SILVER QUALITY GATE

Schema                         PASS
Completeness                   PASS
Uniqueness                     PASS
Referential Integrity          PASS
Freshness                      PASS
Data Quality Score             98.7%

                         ✓ PROMOTE
```

If a critical test fails:

```text
                 SILVER QUALITY GATE

Schema                         PASS
Completeness                   FAIL
Uniqueness                     PASS
Referential Integrity          PASS

                         ✗ BLOCK
```

The platform should automatically prevent downstream promotion.

---

# 23L. Severity Levels

Not every test failure should necessarily stop the pipeline.

Tests should support severity levels:

### CRITICAL

Pipeline blocked.

Example:

> Primary key is missing.

### ERROR

Pipeline blocked by default.

Example:

> 15% of records fail schema validation.

### WARNING

Pipeline may continue.

Example:

> 1% unexpected null values.

### INFORMATIONAL

Record only.

Example:

> Dataset volume increased by 8%.

This should be configurable by dataset and environment.

---

# 23M. Quarantine Zone

The platform shall provide a **quarantine/reject area**.

Bad records should not simply disappear.

```text
                 Source
                   │
                   ▼
               Ingestion
                   │
            ┌──────┴──────┐
            │             │
          PASS           FAIL
            │             │
            ▼             ▼
         Bronze       Quarantine
            │             │
            ▼             ▼
         Silver       Investigation
```

The quarantine area should retain:

- Original record
- Failure reason
- Test that failed
- Timestamp
- Pipeline ID
- Batch ID
- Source
- Error details

This gives engineers the ability to investigate and potentially replay failed records.

---

# 23N. Test Results and Observability

All test executions should be recorded as metadata.

Example:

```text
Dataset: Customer
Pipeline: CRM → Bronze → Silver

Run ID: 983274

Tests:             47
Passed:            45
Warnings:           1
Failed:             1

Status:             BLOCKED

Failure:
customer_id uniqueness

Failed records:
1,247
```

The UI should allow engineers and analysts to drill into the failure.

---

# 23O. Test Automation

Tests should be automatically generated where possible.

This is an excellent opportunity for AI agents.

For example, when the platform discovers:

```text
customer_id
```

the AI agent could recommend:

```text
✓ NOT NULL
✓ UNIQUE
✓ INTEGER
```

For:

```text
email
```

it could recommend:

```text
✓ NOT NULL
✓ EMAIL FORMAT
✓ PII CLASSIFICATION
```

For:

```text
transaction_amount
```

it could recommend:

```text
✓ NOT NULL
✓ >= 0
✓ DECIMAL
```

The data engineer should be able to review and approve the proposed rules.

---

# 23P. AI-Powered Anomaly Detection

Beyond deterministic tests, the platform should eventually support statistical and AI-driven anomaly detection.

For example:

```text
Historical daily records:

98k
101k
103k
99k
102k
100k

Today's records:

17k
```

The platform should detect this as an anomaly even if the schema and traditional quality rules pass.

The agent could report:

> Record volume is 83% below the historical baseline. The pipeline has been blocked from promoting data to Silver.

---

# 23Q. Test-Driven Data Pipeline Development

The platform should encourage **test-first development** for data pipelines.

The preferred development workflow should be:

```text
Define Data Contract
        │
        ▼
Define Tests
        │
        ▼
Develop Transformation
        │
        ▼
Run Tests
        │
        ▼
Deploy
```

rather than:

```text
Build Pipeline
      ↓
Load Data
      ↓
Discover Problems
      ↓
Fix Problems
```

---

# 23R. Environment-Specific Testing

Testing requirements should differ appropriately between environments.

### Development

- Unit tests
- Schema tests
- Transformation tests
- Sample data

### Test/UAT

- Integration tests
- Data reconciliation
- Data quality
- Contract tests
- Performance tests

### Production

- Data quality
- Data freshness
- Contract validation
- Reconciliation
- Anomaly detection
- Security validation

---

# 23S. Promotion Model

The platform should implement explicit promotion states.

```text
INGESTED
   │
   ▼
VALIDATED
   │
   ▼
BRONZE
   │
   ▼
SILVER VALIDATED
   │
   ▼
SILVER
   │
   ▼
GOLD VALIDATED
   │
   ▼
GOLD
   │
   ▼
CONSUMABLE
```

Data should only transition between states when the relevant quality gates pass.

---

# 23T. Manual Override

There must be a controlled mechanism to override a failed quality gate when business circumstances require it.

For example:

> Source system generated 5% additional null values due to a known upstream incident.

An authorised user may override the gate.

The override must require:

- Authorisation
- Reason
- Expiry
- User identity
- Timestamp
- Impact assessment

The platform must never silently bypass a failed test.

---

# 24. Data Lineage

The platform should provide end-to-end lineage.

Example:

```text
CRM.customer
       │
       ▼
Bronze.customer
       │
       ▼
Silver.customer
       │
       ▼
Gold.customer_360
       │
       ├────────► BigQuery
       ├────────► Semantic Layer
       ├────────► API
       └────────► ML Dataset
```

Users should be able to navigate both:

**Upstream lineage**

and

**Downstream lineage**

---

# 25. Metadata and Data Catalog

The platform should maintain a central metadata model containing:

- Dataset
- Table
- Column
- Data type
- Description
- Owner
- Steward
- Classification
- Quality score
- Lineage
- Source
- Refresh frequency
- Last updated
- Usage statistics

The catalog should be searchable.

Example:

> Search: "customer revenue"

Results:

```text
Customer Revenue
Gold
Owner: Customer Analytics
Quality: 98%
Updated: 15 minutes ago
Consumers: Finance, Marketing, ML
```

---

# 26. Web UI

The platform shall provide a modern web-based UI.

The UI should be the primary control plane for users who do not want to interact directly with Terraform or cloud consoles.

Major sections:

```text
Dashboard

Platforms

Data Sources

Pipelines

Datasets

Catalog

Data Quality

Lineage

Semantic Layer

APIs

Monitoring

Agents

Administration
```

---

# 27. Platform Dashboard

The dashboard should provide:

- Platform status
- Cloud
- Environment
- Infrastructure health
- Pipeline health
- Data quality
- Storage utilisation
- Compute utilisation
- Cost
- Recent failures
- Recent deployments

Example:

```text
Lakehouse: Customer Analytics

Cloud: GCP
Region: Sydney

Pipelines       124
Healthy         119
Failed            3
Running           2

Data Quality    97.8%

Storage         18.4 TB

Last Deployment
5 September 2026
```

---

# 28. Data Source Configuration

Users should be able to configure a source through a wizard.

Example:

```text
Add Data Source

Type:
[ PostgreSQL ]

Connection:
Host
Port
Database

Authentication:
[ Secret ]

Tables:
☑ customer
☑ orders
☐ payments

Ingestion:
○ Full
● Incremental
○ CDC

Frequency:
[ Every 15 minutes ]

Target:
[ Bronze ]

[ Validate ] [ Save ] [ Deploy ]
```

The platform should automatically create the required ingestion configuration.

---

# 29. Pipeline Management

Users should be able to:

- Create pipelines
- View pipelines
- Trigger pipelines
- Pause pipelines
- Retry pipelines
- View execution history
- View logs
- View metrics
- View failures

---

# 30. AI Agents

AI should be incorporated as a platform capability rather than simply adding a chatbot.

Potential agents include:

## 30.1 Data Source Agent

Given a source schema, the agent can:

- Understand the schema
- Identify tables
- Recommend ingestion strategy
- Identify primary keys
- Identify incremental columns
- Identify likely sensitive fields
- Recommend partitioning

## 30.2 Ingestion Agent

The agent can recommend:

```text
Full Load
Incremental Load
CDC
Streaming
```

based on source characteristics.

## 30.3 Schema Agent

The agent can detect:

- Schema changes
- New columns
- Removed columns
- Type changes
- Breaking changes

and recommend actions.

## 30.4 Data Quality Agent

The agent can inspect datasets and propose quality rules.

Example:

> `customer.email` appears to contain email addresses.

Recommendation:

```text
Add validation:
email IS VALID
```

## 30.5 Data Documentation Agent

Automatically generate:

- Dataset descriptions
- Column descriptions
- Business descriptions
- Pipeline documentation

## 30.6 Data Engineer Agent

An engineering assistant could generate:

- SQL
- dbt models
- Terraform
- ingestion configuration
- quality rules
- tests

Generated changes must go through validation and approval mechanisms.

## 30.7 Operations Agent

The operations agent should analyse pipeline failures.

Instead of:

> Pipeline failed.

It should provide:

> Pipeline failed because source table `customer` changed column `customer_id` from INTEGER to STRING at 02:14 UTC. Three downstream datasets are affected.

And potentially recommend remediation.

---

# 31. Human-in-the-Loop

AI agents must not have unrestricted production access by default.

Actions should be classified:

### Low risk

Automatically execute:

- Documentation generation
- Metadata enrichment
- Query suggestions

### Medium risk

Require approval:

- Pipeline configuration changes
- Quality rule changes
- Schema changes

### High risk

Require explicit human approval:

- Production infrastructure changes
- Data deletion
- Access changes
- Security policy changes

---

# 32. Observability

The platform shall provide unified observability.

## Pipeline

- Success rate
- Failure rate
- Duration
- Throughput
- Records processed

## Infrastructure

- CPU
- Memory
- Storage
- Network

## Data

- Freshness
- Volume
- Quality

## Cost

- Storage cost
- Compute cost
- Query cost
- Pipeline cost

---

# 33. Alerting

Users should receive alerts for:

- Pipeline failures
- SLA violations
- Data freshness failures
- Data quality degradation
- Schema changes
- Infrastructure failures
- Cost anomalies

Notification channels could include:

- Email
- Slack
- Microsoft Teams
- PagerDuty
- Webhooks

---

# 34. Security Requirements

Security must be designed into the platform.

Requirements include:

- Encryption at rest
- Encryption in transit
- Source-side encryption
- Column-level data protection
- Tokenisation
- Masking
- Secrets management
- IAM integration
- RBAC
- Least privilege
- Network isolation
- Private endpoints where required
- Audit logging
- Credential rotation
- Production access controls

---

# 34A. Data Encryption and Protection

The platform shall provide multiple layers of encryption to protect data throughout its lifecycle.

Encryption shall be supported at:

1. **Source side before transmission**
2. **In transit**
3. **At rest**
4. **Column level**
5. **File/object level where required**

The platform should support encryption without requiring downstream consumers to understand the underlying encryption implementation.

---

# 34B. Source-Side File Encryption

The platform shall support encryption of files **before they leave the source environment**.

This is particularly important for organisations where sensitive data must not exist in plaintext during transmission or outside the source-controlled environment.

The supported pattern should be:

```text
Source Environment
        │
        ▼
┌───────────────────┐
│ Source Files      │
│ CSV / JSON / etc. │
└─────────┬─────────┘
          │
          ▼
┌───────────────────┐
│ Encryption Agent  │
│ / Service         │
└─────────┬─────────┘
          │
          │ Encrypted File
          ▼
     Secure Transfer
          │
          ▼
┌───────────────────┐
│ Cloud Storage     │
│ Bronze             │
└───────────────────┘
```

The platform shall support industry-standard encryption mechanisms and should avoid developing proprietary cryptographic algorithms.

Potential mechanisms should include:

- PGP/GPG
- Envelope encryption
- Public/private key encryption
- Cloud KMS integration
- Customer-managed keys

The exact mechanism should be selected based on source-system requirements and security architecture.

---

# 34C. Source-Side Encryption Agent

For file-based ingestion, the platform should provide a lightweight component that can be deployed close to the data source.

The component could operate as:

- Docker container
- Linux service
- Windows service
- Kubernetes workload
- Serverless component where appropriate

Its responsibilities may include:

1. Detect new files
2. Validate file integrity
3. Identify the appropriate encryption policy
4. Encrypt the file
5. Generate encryption metadata
6. Transfer the encrypted file
7. Verify successful transfer
8. Optionally remove or archive the source file according to policy

---

# 34D. Column-Level Data Protection

The platform shall support protection of individual columns containing sensitive or confidential information.

The platform should support multiple protection mechanisms rather than treating encryption as the only option:

- Encryption
- Tokenisation
- Masking
- Hashing where one-way identification is appropriate
- Redaction for appropriate file/document use cases
- Pseudonymisation

The choice of mechanism should be policy-driven.

Example:

```text
Customer
────────────────────────────────
customer_id       tok_8f71a
name              <masked/encrypted>
email             tok_92ab3
phone             tok_41cd9
date_of_birth     <encrypted>
country           Australia
```

---

# 34E. Tokenisation

For highly sensitive data, the platform should support tokenisation.

Tokenisation should replace sensitive values with tokens while keeping the original value within an appropriately secured token vault or tokenisation service.

Example:

```text
Source

Customer ID: 123456
Email: ali@example.com
Phone: 0412345678
```

becomes:

```text
Lakehouse

Customer ID: tok_8f71a
Email: tok_92ab3
Phone: tok_41cd9
```

The platform should support deterministic tokenisation where business requirements require joins or matching without exposing the underlying sensitive value.

Tokenisation should be evaluated particularly for PII and other highly sensitive attributes consumed by analytics, data science and ML teams.

---

# 34F. Encryption Policies

Users should be able to define data protection policies through the platform UI.

Example:

```text
Data Protection Policy

Dataset:
Customer

Column:
email

Classification:
RESTRICTED

Protection:
Tokenisation

Key / Token Service:
Customer-PII-Protection

Masking:
Enabled

Detokenisation:
Restricted

Approved Roles:
Customer Analytics
Customer Service
```

The policy should be automatically propagated to relevant ingestion and transformation processes.

---

# 34G. Encryption and Data Classification

Encryption and data protection policies should integrate with the platform's data classification capability.

Example:

```text
Classification          Protection
─────────────────────────────────────────
PUBLIC                  None
INTERNAL                Standard encryption
CONFIDENTIAL            Encryption
RESTRICTED              Column encryption/tokenisation
HIGHLY RESTRICTED       Column + file encryption
```

The platform should allow organisations to define their own classification-to-protection mappings.

---

# 34H. Key Management

Encryption keys shall be managed through approved Key Management Systems rather than stored directly in application configuration.

The platform should support integration with:

### AWS

- AWS KMS
- Secrets Manager where appropriate

### GCP

- Cloud KMS
- Secret Manager where appropriate

The platform should also consider support for an external enterprise key-management solution.

Requirements should include:

- Key rotation
- Key versioning
- Key lifecycle management
- Access control
- Key usage auditing
- Key revocation
- Separation of duties

---

# 34I. Encryption Key Abstraction

Because the platform is cloud independent, encryption should be abstracted at the logical platform level.

```text
                Platform Encryption Service
                         │
             ┌───────────┴───────────┐
             │                       │
          AWS KMS                GCP KMS
             │                       │
          AWS Key                  GCP Key
```

A platform configuration should therefore be able to specify:

```yaml
encryption:
  enabled: true
  mode: column
  key_management: managed
  key_policy: restricted-data
```

without requiring the user to understand the underlying cloud-specific KMS implementation.

---

# 34J. Encryption in Transit

All data transferred between systems must use secure encrypted communication.

Requirements include:

- TLS
- Secure API communication
- Secure database connections
- Secure file transfer
- Certificate management
- Certificate rotation

Where the source environment supports it, the platform should support private network connectivity rather than transferring sensitive data across the public internet.

---

# 34K. Encryption at Rest

All lakehouse storage must support encryption at rest.

This should include:

- Bronze
- Silver
- Gold
- Metadata
- Logs where sensitive data may be present
- Temporary storage
- Backup storage

The platform should support both:

**Platform-managed keys**

and

**Customer-managed keys (CMK)**

where required.

---

# 34L. Encryption-Aware Data Lineage

The metadata and lineage system should record the protection state of sensitive data.

For example:

```text
Source
Customer.email
      │
      │ Encrypted
      ▼
Bronze
customer.email
      │
      │ Protected
      ▼
Silver
customer.email
      │
      │ Protected
      ▼
Gold
customer.email
```

The catalog should indicate:

- Classification
- Encryption status
- Protection mechanism
- Key reference
- Masking status
- Tokenisation status
- Authorised access roles

Actual encryption keys must **never** be exposed through the catalog or UI.

---

# 34M. Secure Data Access

Encryption should not be treated as a replacement for access control.

The platform must enforce:

```text
Identity
    ↓
Authentication
    ↓
Authorisation
    ↓
Data Classification
    ↓
Encryption / Tokenisation / Masking Policy
    ↓
Data Access
```

Where decryption or detokenisation is required, the platform should ensure that the requesting user or workload has the appropriate permission to use the relevant key or tokenisation service.

---

# 34N. AI Agent Security

AI agents must not be permitted to bypass encryption or security policies.

For example, an AI agent may identify:

> `customer.email` appears to contain sensitive information.

It can recommend:

```text
Classification: RESTRICTED
Protection: Tokenisation
```

However, the agent must not independently:

- Retrieve encryption keys
- Decrypt restricted data
- Detokenise restricted data
- Change encryption policies
- Grant access
- Disable encryption
- Export decrypted sensitive data

unless explicitly authorised under the platform's security and approval model.

---

# 34O. Secure File Transfer

The ingestion framework shall support secure transfer mechanisms for encrypted files.

Potential mechanisms include:

- SFTP
- HTTPS
- Cloud-native secure transfer
- Private network connectivity
- Object storage transfer mechanisms

The platform should validate:

- File integrity
- File signature/checksum
- Encryption status
- File authenticity
- Transfer completion

before making the file available for downstream processing.

---

# 34P. Security Auditability

All security-sensitive operations shall be auditable.

Audit events should include:

- Encryption
- Decryption
- Tokenisation
- Detokenisation
- Key usage
- Key rotation
- Policy changes
- Access to encrypted columns
- Access to restricted datasets
- File transfers
- Failed decryption attempts
- Changes to encryption configuration

Example:

```text
2026-09-05 14:22
User: DataPipelineService
Dataset: Customer
Column: email
Action: DETOKENISE
Purpose: Approved downstream transformation
Result: SUCCESS
Protection: customer-pii-token-service
```

---

# 35. CI/CD

The platform should support GitOps principles.

Changes to:

- Terraform
- Pipelines
- Data models
- Quality rules
- Semantic models
- Configuration

should be version controlled.

Preferred flow:

```text
Developer
    │
    ▼
Git
    │
    ▼
Pull Request
    │
    ▼
Validation
    │
    ├── Terraform validation
    ├── Unit tests
    ├── Data tests
    ├── Security checks
    └── Policy checks
    │
    ▼
Approval
    │
    ▼
Deployment
```

---

# 36. Disaster Recovery

The platform should support:

- Backup
- Recovery
- Infrastructure recreation
- Data replication where required
- Metadata recovery
- Configuration recovery

The target should be:

> Infrastructure should be reproducible from code.

---

# 37. Portability Requirements

A critical product requirement is that moving from AWS to GCP should not require rebuilding the data platform.

For example:

```text
        Logical Platform
              │
       ┌──────┴──────┐
       ▼             ▼
      AWS            GCP
       │             │
    S3 etc.       GCS etc.
```

Business logic, metadata, ingestion definitions and logical datasets should remain portable wherever practical.

---

# 38. Self-Service Philosophy

A central product principle should be:

> **The platform team builds capabilities once; data teams consume those capabilities repeatedly.**

A data engineer should not need to create:

- IAM policies
- Buckets
- Networking
- Monitoring
- Ingestion infrastructure
- Orchestration
- Catalog configuration

for every new project.

Instead:

```text
Create Platform
       ↓
Configure Source
       ↓
Select Tables
       ↓
Configure Ingestion
       ↓
Define Tests
       ↓
Configure Protection
       ↓
Deploy
       ↓
Data Available
```

---

# 39. Example End-to-End User Journey

A data engineer wants to ingest a SQL Server database.

### Step 1

Open the platform UI.

### Step 2

Select:

```text
Create Data Platform
Cloud = AWS
Region = Sydney
Environment = Production
```

### Step 3

Platform is automatically provisioned.

### Step 4

Select:

```text
Add Data Source
SQL Server
```

### Step 5

Enter connection information.

### Step 6

Platform discovers the schema.

The AI agent analyses:

```text
customer
orders
products
payments
```

### Step 7

Agent recommends:

```text
customer → CDC
orders → incremental
products → daily full
payments → CDC
```

### Step 8

Agent recommends data protection:

```text
customer.email → tokenisation
customer.phone → tokenisation
customer.date_of_birth → encryption
```

### Step 9

Platform recommends tests:

```text
customer.customer_id → NOT NULL + UNIQUE
orders.order_id → NOT NULL + UNIQUE
orders.customer_id → referential integrity
orders.amount → >= 0
```

### Step 10

User approves.

### Step 11

Platform creates ingestion pipelines and associated quality gates.

### Step 12

Data lands in:

```text
Bronze
```

Only data that passes the Bronze quality gate is eligible for Silver processing.

### Step 13

Transformation moves validated data into:

```text
Silver
```

### Step 14

Silver tests run. Failed records are quarantined and promotion is blocked where required.

### Step 15

Business models produce:

```text
Gold
```

### Step 16

Gold quality and business reconciliation tests run.

### Step 17

The datasets become available through:

```text
DuckDB
Data Warehouse
Semantic Layer
API
```

### Step 18

AI/ML teams discover the datasets through the catalog.

---

# 40. Non-Functional Requirements

## Performance

The platform should support:

- Large datasets
- Concurrent users
- Parallel ingestion
- Large-scale transformations

## Availability

Production platform components should meet agreed organisational availability targets.

## Scalability

The platform should scale independently across:

- Storage
- Compute
- Ingestion
- Query workloads

## Maintainability

Components should be independently deployable where practical.

## Extensibility

The platform should support new:

- Clouds
- Sources
- Query engines
- Catalogs
- AI models
- Agents

without major architectural changes.

## Security

Security controls must not materially reduce the ability of authorised users to consume data.

## Cost efficiency

The platform should provide mechanisms to monitor and optimise:

- Storage
- Compute
- Query
- Ingestion
- Data transfer
- AI/LLM usage

---

# 41. MVP Scope

The platform should **not attempt to build everything above in V1**.

The MVP should establish the core platform.

## MVP Phase 1

### Infrastructure

- AWS
- GCP
- Terraform
- Object storage
- Networking
- IAM

### Lakehouse

- Bronze
- Silver
- Gold
- Apache Iceberg evaluation

### Ingestion

- PostgreSQL
- SQL Server
- CSV
- S3/GCS files

### Processing

- DuckDB
- One scalable cloud query/compute engine

### Orchestration

- Standard pipeline orchestration

### Testing

- Schema validation
- Data contracts
- Data quality rules
- Quality gates
- Quarantine
- Basic reconciliation
- Freshness checks

### Security

- Encryption at rest
- Encryption in transit
- Source-side file encryption
- Basic column protection
- Key management integration

### UI

- Platform creation
- Data source configuration
- Pipeline monitoring
- Dataset browsing
- Quality monitoring

### Governance

- Basic metadata
- Ownership
- Data quality
- Lineage

---

# 42. Phase 2

Add:

- Airbyte integration
- CDC
- Advanced tokenisation
- APIs
- Semantic layer
- Data warehouse integration
- Advanced governance
- Data catalog
- Cost management
- Advanced observability
- Advanced data contracts
- Statistical anomaly detection

---

# 43. Phase 3

Add:

- AI agents
- Automated schema management
- AI-assisted pipeline creation
- AI-assisted data quality
- AI operations
- Natural language data discovery
- Automated optimisation
- AI-assisted data protection classification
- AI-assisted test generation

---

# 44. Success Metrics

The platform should be measured through business outcomes rather than infrastructure metrics alone.

## Platform deployment

Target:

> New lakehouse environment deployed in less than 30 minutes.

## Data onboarding

Target:

> Common data source onboarded in less than 30 minutes.

## Engineering effort

Target:

> 70–90% reduction in custom ingestion code for supported sources.

## Data quality

Target:

> 100% of production datasets have automated quality gates appropriate to their layer.

## Data contamination

Target:

> Zero knowingly failed quality-gated datasets promoted to downstream layers.

## Engineering remediation

Target:

> Majority of data quality failures detected at ingestion or before downstream promotion.

## Reusability

Target:

> Majority of data pipelines built using standard platform capabilities.

## Reliability

Target:

> >99% successful pipeline executions for stable sources.

## Time to data

Measure:

> Source availability → Bronze → Silver → Gold → consumer availability.

## Adoption

Measure:

- Number of teams
- Number of datasets
- Number of pipelines
- Number of consumers
- Number of API consumers

---

# 45. Architectural Decision Areas

The engineering and architecture teams should explicitly evaluate the following before locking the technology stack.

| Decision | Options to evaluate |
|---|---|
| Table format | Iceberg / Delta / Hudi |
| Ingestion | Airbyte / custom / cloud-native |
| Query engine | DuckDB / Trino / cloud engines |
| Transformation | dbt / Spark / SQL |
| Orchestration | Airflow / Dagster / cloud-native |
| Catalog | OpenMetadata / DataHub / cloud catalog |
| Quality | Great Expectations / Soda / dbt tests / custom |
| Semantic layer | Cube / dbt Semantic Layer / other |
| Metadata | Custom / OpenMetadata / DataHub |
| API layer | Custom / gateway-based |
| Agent framework | LangGraph / OpenAI Agents SDK / other |
| Compute | Serverless / containers / Spark |
| Streaming | Kafka / cloud-native messaging |
| Encryption | Cloud KMS / external KMS / envelope encryption |
| Tokenisation | Managed tokenisation service / enterprise vault / custom service |
| Data protection | Encryption / tokenisation / masking / pseudonymisation |
| Observability | OpenTelemetry + cloud services |

The important requirement is that these decisions should be driven by **portability, operational simplicity, cost, interoperability and long-term maintainability**, rather than selecting technologies because they are currently popular.

---

# 46. Most Important Architectural Principle

> **Do not build a "cloud-independent" platform by creating a lowest-common-denominator abstraction that prevents teams from taking advantage of cloud capabilities.**

Instead, use a **portable core with cloud-specific implementations where they provide meaningful value.**

For example:

```text
                    PLATFORM API
                         │
          ┌──────────────┼──────────────┐
          │              │              │
       Storage        Compute       Identity
          │              │              │
      ┌───┴───┐      ┌───┴───┐      ┌───┴───┐
      AWS     GCP     AWS     GCP     AWS    GCP
```

This gives you portability without sacrificing capability.

---

# 47. Product Definition

Ultimately, the product is:

> **A self-service, AI-enabled, cloud-independent data platform that provisions a governed lakehouse, connects enterprise data sources, manages data through Bronze, Silver and Gold layers, enforces shift-left data quality and security gates, protects sensitive data through encryption and tokenisation, and exposes trusted data through query engines, warehouses, semantic models and APIs.**

The ideal user experience is:

```text
                    ONE PLATFORM
                         │
             ┌───────────┴───────────┐
             │                       │
           AWS                      GCP
             │                       │
             └───────────┬───────────┘
                         │
                  LAKEHOUSE CORE
                         │
              ┌──────────┴──────────┐
              │                     │
            INGEST               GOVERN
              │                     │
              ▼                     ▼
           BRONZE              CATALOG
              │                QUALITY
              │                LINEAGE
              │                IAM
              ▼                SECURITY
           SILVER
              │
              ▼
            GOLD
              │
      ┌───────┼────────┬─────────┐
      ▼       ▼        ▼         ▼
    Query   Warehouse Semantic   APIs
             │        Layer
      └───────┴────────┼─────────┘
                       ▼
              AI / ML / BI / Apps
```

---

# 48. Core Product Principles Summary

The platform should be governed by the following principles:

1. **One-click deployment**
2. **Cloud independence**
3. **Infrastructure as Code**
4. **Medallion Architecture**
5. **Open lakehouse standards**
6. **Self-service ingestion**
7. **Reuse before custom development**
8. **Shift-left data quality**
9. **Quality gates before promotion**
10. **Quarantine rather than propagation**
11. **Data contracts**
12. **Security by design**
13. **Encryption by default**
14. **Tokenisation for appropriate sensitive data**
15. **Policy-driven data protection**
16. **End-to-end lineage**
17. **Metadata-driven platform**
18. **Semantic consistency**
19. **AI/ML as first-class consumers**
20. **AI agents with human oversight**
21. **GitOps and CI/CD**
22. **Observable by default**
23. **Cost-aware by design**
24. **Portable core with cloud-specific optimisation**
25. **Everything reproducible through code and configuration**

---

# 49. Final Business Requirement

The organisation requires a **modern, cloud-independent, self-service Data Lakehouse Platform** that allows teams to provision and operate a governed data platform with minimal engineering effort.

The platform must:

- Deploy consistently across AWS and GCP.
- Use Terraform for infrastructure provisioning.
- Implement a Bronze, Silver and Gold Medallion Architecture.
- Ingest data from databases, files, APIs, SaaS and streaming sources.
- Prefer reusable ingestion frameworks such as Airbyte where appropriate.
- Support open lakehouse technologies such as Apache Iceberg.
- Evaluate DuckDB for lightweight analytics and direct lakehouse querying.
- Provide direct analyst access to Silver and Gold datasets.
- Implement shift-left testing and data contracts.
- Prevent failed or invalid data from being promoted downstream.
- Provide quarantine and replay mechanisms.
- Provide automated quality gates at every lakehouse layer.
- Support data reconciliation, freshness, schema and business-rule testing.
- Provide metadata, cataloguing and lineage.
- Provide a semantic layer for consistent business definitions.
- Provide warehouse, API, AI/ML and data science consumption paths.
- Provide comprehensive observability and operational management.
- Protect data using encryption, tokenisation, masking and other appropriate mechanisms.
- Support encryption of files at the source before transfer to cloud environments.
- Support column-level protection for sensitive data.
- Integrate with cloud and enterprise key-management systems.
- Provide a modern, user-friendly Web UI.
- Use AI agents to automate appropriate engineering, governance and operational tasks.
- Maintain human approval for security-sensitive and production-impacting AI actions.
- Support GitOps, CI/CD and infrastructure reproducibility.
- Optimise for portability, scalability, security, operational simplicity and cost.

The resulting platform should enable the organisation to move from **"build a data pipeline"** to **"configure and deploy a governed data product"**, significantly reducing the time and engineering effort required to make trusted data available to downstream consumers.
