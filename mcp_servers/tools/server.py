"""
Tools MCP Server — exposes KYC and mule investigation tools as MCP tools
for any external MCP-compatible client.

Architecture:
  External MCP Client → Tools MCP Server → Tool implementations
  (Agents call the same tool classes directly via Python during pipeline execution)

KYC Screening tools:
  - crm_search: Search CRM by customer name
  - crm_get: Get customer by ID
  - crm_register: Register a new customer
  - identity_verify: Verify customer identity documents
  - screening_screen: Screen name against sanctions/PEP lists
  - screening_adverse_media: Search adverse media
  - jurisdiction_risk: Look up jurisdiction risk level

Mule Account Hunting tools:
  - transaction_history: Get transaction history for an account
  - transaction_velocity: Get transaction velocity stats
  - detect_structuring: Detect structuring patterns
  - network_links: Get linked accounts via graph traversal
  - check_mule_network: Check if account is in a known mule network
  - fraud_intel_check: Check account in fraud intelligence database
  - match_typology: Match indicators to known scam typologies
"""
import json
import logging
import sys
from pathlib import Path

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_ROOT))

logger = logging.getLogger("tools_mcp")


def create_server() -> Server:
    server = Server("kyc-tools")

    # Lazy-load and instantiate tools to avoid import issues at startup
    def _get_kyc_tools():
        from tools.crm_tool import CRMTool
        from tools.identity_tool import IdentityVerificationTool
        from tools.screening_tool import SanctionsScreeningTool
        return CRMTool(), IdentityVerificationTool(), SanctionsScreeningTool()

    def _get_mule_tools():
        from tools.transaction_tool import TransactionTool
        from tools.network_graph_tool import NetworkGraphTool
        from tools.fraud_intelligence_tool import FraudIntelligenceTool
        return TransactionTool(), NetworkGraphTool(), FraudIntelligenceTool()

    @server.list_tools()
    async def list_tools() -> list[Tool]:
        return [
            # ── CRM Tools ────────────────────────────────────────────────
            Tool(
                name="crm_search",
                description="Search CRM database by customer name. Returns matching customer records with confidence scores.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "name": {"type": "string", "description": "Customer name to search"},
                    },
                    "required": ["name"],
                },
            ),
            Tool(
                name="crm_get",
                description="Get customer record by customer ID.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "customer_id": {"type": "string", "description": "Customer ID (e.g. C001)"},
                    },
                    "required": ["customer_id"],
                },
            ),
            Tool(
                name="crm_register",
                description="Register a new customer in the CRM.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "customer": {"type": "object", "description": "Customer record dict"},
                    },
                    "required": ["customer"],
                },
            ),
            # ── Identity Tools ───────────────────────────────────────────
            Tool(
                name="identity_verify",
                description="Verify customer identity documents (HKID, passport, etc.) against government registries.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "id_type": {"type": "string", "description": "Document type (HKID, PASSPORT, etc.)"},
                        "id_number": {"type": "string", "description": "Document number"},
                        "full_name": {"type": "string", "description": "Customer full name"},
                        "date_of_birth": {"type": "string", "description": "Date of birth (YYYY-MM-DD)"},
                    },
                    "required": ["id_type", "id_number", "full_name"],
                },
            ),
            Tool(
                name="identity_verify_ubo",
                description="Verify beneficial ownership structure for corporate entities.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "customer_id": {"type": "string"},
                        "company_name": {"type": "string"},
                    },
                    "required": ["customer_id"],
                },
            ),
            # ── Screening Tools ──────────────────────────────────────────
            Tool(
                name="screening_screen",
                description="Screen name variants against sanctions lists (UN, OFAC, EU, HKMA) and PEP databases.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "name_variants": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "List of name variants to screen",
                        },
                        "date_of_birth": {"type": "string", "description": "DOB for confidence boosting"},
                        "nationality": {"type": "string", "description": "Nationality code for confidence boosting"},
                    },
                    "required": ["name_variants"],
                },
            ),
            Tool(
                name="screening_adverse_media",
                description="Search adverse media articles for a customer name.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "name": {"type": "string", "description": "Customer name to search"},
                    },
                    "required": ["name"],
                },
            ),
            Tool(
                name="jurisdiction_risk",
                description="Look up FATF jurisdiction risk classification.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "jurisdiction_code": {"type": "string", "description": "ISO 3166-1 alpha-3 country code"},
                    },
                    "required": ["jurisdiction_code"],
                },
            ),
            # ── Mule Investigation Tools ─────────────────────────────────
            Tool(
                name="transaction_history",
                description="Get transaction history for a mule investigation account.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "account_id": {"type": "string", "description": "Account ID (e.g. M001)"},
                        "limit": {"type": "integer", "description": "Max transactions to return (default 50)"},
                    },
                    "required": ["account_id"],
                },
            ),
            Tool(
                name="transaction_velocity",
                description="Get transaction velocity stats (pass-through ratio, same-day credit/debit, etc.).",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "account_id": {"type": "string", "description": "Account ID"},
                    },
                    "required": ["account_id"],
                },
            ),
            Tool(
                name="detect_structuring",
                description="Detect structuring patterns — transactions deliberately kept just below HKD 50,000 threshold.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "account_id": {"type": "string", "description": "Account ID"},
                    },
                    "required": ["account_id"],
                },
            ),
            Tool(
                name="network_links",
                description="Discover linked accounts via graph traversal (max depth 2).",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "account_id": {"type": "string", "description": "Account ID"},
                        "max_depth": {"type": "integer", "description": "Traversal depth (default 2)"},
                    },
                    "required": ["account_id"],
                },
            ),
            Tool(
                name="check_mule_network",
                description="Check whether an account is a member of any known mule network.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "account_id": {"type": "string", "description": "Account ID"},
                    },
                    "required": ["account_id"],
                },
            ),
            Tool(
                name="fraud_intel_check",
                description="Check account against the fraud intelligence database (known mules, adverse intel).",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "account_id": {"type": "string", "description": "Account ID"},
                    },
                    "required": ["account_id"],
                },
            ),
            Tool(
                name="match_typology",
                description="Match observed indicators against known scam typologies.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "indicators": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "List of observed behavioural indicators",
                        },
                    },
                    "required": ["indicators"],
                },
            ),
        ]

    @server.call_tool()
    async def call_tool(name: str, arguments: dict) -> list[TextContent]:
        CRMTool, IdentityVerificationTool, SanctionsScreeningTool = _get_kyc_tools()

        try:
            if name == "crm_search":
                results = CRMTool.search_by_name(arguments["name"])
                return [TextContent(type="text", text=json.dumps(results, default=str))]

            elif name == "crm_get":
                result = CRMTool.get_customer(arguments["customer_id"])
                return [TextContent(type="text", text=json.dumps(result, default=str))]

            elif name == "crm_register":
                CRMTool.register_customer(arguments["customer"])
                return [TextContent(type="text", text=json.dumps({"status": "registered"}))]

            elif name == "identity_verify":
                result = IdentityVerificationTool.verify_identity(
                    id_number=arguments["id_number"],
                    full_name=arguments["full_name"],
                    dob=arguments.get("date_of_birth", ""),
                )
                return [TextContent(type="text", text=json.dumps(result, default=str))]

            elif name == "identity_verify_ubo":
                result = IdentityVerificationTool.verify_beneficial_owner_structure(
                    entity_name=arguments.get("company_name", arguments["customer_id"]),
                )
                return [TextContent(type="text", text=json.dumps(result, default=str))]

            elif name == "screening_screen":
                result = SanctionsScreeningTool.screen(
                    queries=arguments["name_variants"],
                    customer_data={
                        "date_of_birth": arguments.get("date_of_birth", ""),
                        "nationality": arguments.get("nationality", ""),
                    },
                )
                return [TextContent(type="text", text=json.dumps(result, default=str))]

            elif name == "screening_adverse_media":
                result = SanctionsScreeningTool.search_adverse_media(arguments["name"])
                return [TextContent(type="text", text=json.dumps(result, default=str))]

            elif name == "jurisdiction_risk":
                result = CRMTool.get_jurisdiction_risk(arguments["jurisdiction_code"])
                return [TextContent(type="text", text=json.dumps(result, default=str))]

            # ── Mule Investigation Tool calls ─────────────────────────────
            elif name in (
                "transaction_history", "transaction_velocity", "detect_structuring",
                "network_links", "check_mule_network", "fraud_intel_check", "match_typology",
            ):
                TxTool, NetTool, FraudTool = _get_mule_tools()

                if name == "transaction_history":
                    result = TxTool.get_transactions(
                        arguments["account_id"],
                        limit=arguments.get("limit", 50),
                    )
                elif name == "transaction_velocity":
                    result = TxTool.get_velocity(arguments["account_id"])
                elif name == "detect_structuring":
                    result = TxTool.detect_structuring(arguments["account_id"])
                elif name == "network_links":
                    result = NetTool.get_linked_accounts(
                        arguments["account_id"],
                        max_depth=arguments.get("max_depth", 2),
                    )
                elif name == "check_mule_network":
                    result = NetTool.check_known_networks(arguments["account_id"])
                elif name == "fraud_intel_check":
                    mule_check = FraudTool.check_account(arguments["account_id"])
                    intel = FraudTool.get_adverse_intelligence(arguments["account_id"])
                    result = {"mule_check": mule_check, "adverse_intel": intel}
                elif name == "match_typology":
                    result = FraudTool.match_typology(arguments["indicators"])
                else:
                    result = {"error": f"Unknown mule tool: {name}"}

                return [TextContent(type="text", text=json.dumps(result, default=str))]

            else:
                return [TextContent(type="text", text=json.dumps({"error": f"Unknown tool: {name}"}))]

        except Exception as e:
            logger.error("Tool MCP error (%s): %s", name, e)
            return [TextContent(type="text", text=json.dumps({"error": str(e), "tool": name}))]

    return server


async def main():
    server = create_server()
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
