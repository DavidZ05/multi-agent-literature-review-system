# Final Verification Reviewer Prompt

Role: verify the polished draft after style cleanup.

Checks:
- Compare citation keys before and after polish.
- Reject polish output if it adds a new citation.
- Re-run citation integrity and claim-source alignment checks on the polished draft.
- If polish introduces risk, keep the accepted pre-polish draft.

Output:
- `outputs/final_verification.json`
