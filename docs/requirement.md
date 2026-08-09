# Background

Everyone's building AI agents, but the real magic happens when those agents have complete context to act on organizational data. Without reliable knowledge of schemas, lineage, ownership, ML metadata, and governance, agents hallucinate or get stuck on tasks any data engineer could finish in minutes.

That's where DataHub comes in.

DataHub is the open-source context platform that gives AI agents a complete understanding of your data stack — from raw tables to ML models. With an MCP Server, end-to-end ML lineage, and DataHub Skills that give agents direct access to catalog workflows, DataHub turns the modern data ecosystem into something agents can actually work with.

This hackathon is your invitation to build on that foundation. Whether you're shipping autonomous agents, generating production data code, protecting ML models, or building something entirely new — show us what's possible when agents have context.

DataHub powers data stacks at Apple, Pinterest, Netflix, and hundreds of other companies. The most adopted open-source metadata platform — and now the one agents need to do real work.

Ready to build agents that actually ship?

Check out the Resources tab for docs, SDKs, sample datasets, and starter kits. Then start building.

# REQUIREMENTS

## WHAT TO BUILD

Create a working software application that uses DataHub to solve one of the challenges below. Pick one of the four challenges (or combine them):

Agents That Do Real Work: Build AI agents that handle data problems — alone or as a team. Your agent reads DataHub through the MCP Server or Agent Context Kit to understand what's connected to what, takes action, and writes results back so the next person or agent inherits the knowledge.
Metadata-Aware Code Generation & Development: Build agents that generate production data code — transformation models, pipeline DAGs (Airflow, Prefect, Dagster), ingestion scripts, helper scripts, configurations, migration code — that works on the first try because they use DataHub Skills or the MCP Server to read DataHub for the real schemas, lineage, and rules before generating anything. The artifact lives in a Git repo, goes into a PR, and your data team would actually merge it. Strong submissions include sample generated artifacts so judges can see the quality of the output.
Production ML Agents: Build agents for ML teams that protect models in production. Use DataHub's end-to-end ML lineage — the path from training data to features to models to deployments — accessed via the Agent Context Kit or MCP Server to catch silent problems that can break ML systems before they cost money. 
Open / Wildcard: Build anything creative that uses DataHub as the foundation — supply chain optimization, financial forecasting, regulatory automation, knowledge capture, or anything else. Use whatever fits from DataHub's open-source stack (MCP Server, Agent Context Kit, DataHub Skills, Analytics Agent, or any other DataHub product).


## WHAT TO SUBMIT

Include a URL to your Project that gives judges easy access to test the functionality — a live demo, hosted app, or your repo with clear setup instructions.
Provide a URL to your public code repository for judging and testing. The repository must contain all necessary source code, assets, and full instructions required for the project to be functional. The repository must be public and open source by including an Apache 2.0 open source license file. This license should be detectable and visible at the top of the repository page (in the About section).
Include a text description that summarizes your Project that might include describing its features, functionality, technologies, and data you used.
Include a demonstration video of your Project that is under 3 minutes, uploaded to YouTube or Vimeo with public visibility enabled. The video should include footage that shows the Project functioning and in action.
Optional: Include Sample outputs. If your Project generates artifacts such as code files, queries, reports, or transformations, include examples in your repository (e.g., an examples/ folder) so judges can evaluate the quality without needing to run the code.

# JUDGING CRITERIA

Use of DataHub
How meaningfully does the project use DataHub — its context graph, MCP Server, Agent Context Kit, DataHub Skills, or Analytics Agent? Strong submissions go beyond reading metadata and contribute back to the graph where appropriate.
Technical Execution
Quality of implementation, robustness, and whether the project actually works end-to-end. Does the code do what the submission claims?
Originality
How creative and novel is the approach? Submissions should clearly go beyond features DataHub already provides out of the box. Building on top of, extending, or composing shipped features is welcome; rebuilding them as if from scratch isn't.
Real-World Usefulness
Would a real data, ML, or AI platform team see clear value in this? Submissions don't need to be production-ready, but they should solve a problem practitioners actually face.
Submission Quality
Quality of the demo video, written description, and README. A judge should be able to understand what the project does, why it matters, and find clear setup instructions to try it themselves.
Bonus: Meaningful Open-Source Contribution:
Submissions that include meaningful open-source contributions to DataHub (new connectors, skills, fixes, RFCs, or documentation improvements) will be looked on favorably. Existing contributions extended for the hackathon also count.