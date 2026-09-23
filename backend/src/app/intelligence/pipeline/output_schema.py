from copy import deepcopy

from agents import AgentOutputSchema


class EvidenceOutputSchema(AgentOutputSchema):
    """Constrain generated references to this request, keeping domain validation intact."""

    def __init__(self, output_type, payload):
        super().__init__(output_type)
        segments = [
            segment
            for field in ("targets", "context_only", "evidence", "segments")
            for segment in getattr(payload, field, [])
        ]
        self.segment_ids = sorted({s.id for s in segments})
        self.participant_ids = sorted({p.id for p in getattr(payload, "participants", [])})

    def json_schema(self):
        schema = deepcopy(super().json_schema())
        definitions = schema.setdefault("$defs", {})
        if self.segment_ids:
            # Reuse a single enum: repeated enums can exceed provider schema limits.
            definitions["SuppliedEvidenceId"] = {"type": "string", "enum": list(self.segment_ids)}
        if self.participant_ids:
            definitions["SuppliedParticipantId"] = {
                "type": "string",
                "enum": list(self.participant_ids),
            }

        def visit(node):
            if isinstance(node, dict):
                for name, value in node.get("properties", {}).items():
                    if name in ("source_segment_ids", "evidence_segment_ids"):
                        if self.segment_ids:
                            value["items"] = {"$ref": "#/$defs/SuppliedEvidenceId"}
                        else:
                            value["maxItems"] = 0
                    elif name in ("assignee_participant_id", "participant_id"):
                        node["properties"][name] = (
                            {"anyOf": [{"$ref": "#/$defs/SuppliedParticipantId"}, {"type": "null"}]}
                            if self.participant_ids
                            else {"type": "null"}
                        )
                    elif name == "candidate_participant_ids":
                        if self.participant_ids:
                            value["items"] = {"$ref": "#/$defs/SuppliedParticipantId"}
                        else:
                            value["maxItems"] = 0
                for value in node.values():
                    visit(value)
            elif isinstance(node, list):
                for value in node:
                    visit(value)

        visit(schema)
        return schema
