from fastapi import APIRouter
from fastapi.responses import JSONResponse

from src import constants
import logging

router = APIRouter()
logger = logging.getLogger(__name__)


@router.post("/validate", tags=["FHIR Utilities"])
async def validate_fhir_bundle(payload: dict) -> JSONResponse:
    issues = []
    try:
        if payload.get("resourceType") != "Bundle":
            issues.append({"severity": "error", "field": "resourceType", "message": "Must be 'Bundle'"})

        if payload.get("type") != "collection":
            issues.append({"severity": "warning", "field": "type", "message": "Expected bundle type 'collection'"})

        entries = payload.get("entry", [])
        resource_types = [e.get("resource", {}).get("resourceType") for e in entries]

        if "InsurancePlan" not in resource_types:
            issues.append({"severity": "error", "field": "entry", "message": "No InsurancePlan resource found in bundle"})
        else:
            plan = next(e["resource"] for e in entries if e.get("resource", {}).get("resourceType") == "InsurancePlan")
            for required_field in ["name", "status", "ownedBy", "identifier"]:
                if not plan.get(required_field):
                    issues.append({
                        "severity": "error",
                        "field": f"InsurancePlan.{required_field}",
                        "message": f"Required field '{required_field}' is missing or empty"
                    })
            if not plan.get("meta", {}).get("profile"):
                issues.append({"severity": "warning", "field": "InsurancePlan.meta.profile", "message": "No profile URL set on InsurancePlan"})
            if not plan.get("text"):
                issues.append({"severity": "info", "field": "InsurancePlan.text", "message": "Narrative text is absent"})

        if "Organization" not in resource_types:
            issues.append({"severity": "error", "field": "entry", "message": "No Organization resource found in bundle"})

        return JSONResponse(content={
            "valid": len([i for i in issues if i["severity"] == "error"]) == 0,
            "issue_count": len(issues),
            "issues": issues,
        }, status_code=200)

    except Exception as e:
        logger.exception(constants.LOG_CLAIM_FHIR_VALIDATION_ERROR)
        return JSONResponse(content={"error": {"code": constants.ERROR_CODE_VALIDATION_ERROR, "message": str(e)}}, status_code=400)


@router.post("/bundle-summary", tags=["FHIR Utilities"])
async def get_bundle_summary(payload: dict) -> JSONResponse:
    try:
        entries = payload.get("entry", [])
        resources = {}
        for e in entries:
            r = e.get("resource", {})
            rt = r.get("resourceType", "Unknown")
            resources.setdefault(rt, []).append(r)

        plan = (resources.get("InsurancePlan") or [{}])[0]
        orgs = resources.get("Organization", [])

        owned_by_ref = (plan.get("ownedBy") or {}).get("reference", "")
        insurer = next((o for o in orgs if f"urn:uuid:{o.get('id')}" == owned_by_ref), orgs[0] if orgs else {})

        admin_by_ref = (plan.get("administeredBy") or {}).get("reference", "")
        tpa = next((o for o in orgs if f"urn:uuid:{o.get('id')}" == admin_by_ref), None)

        period = plan.get("period", {})
        plan_type_coding = ((plan.get("type") or [{}])[0].get("coding") or [{}])[0]

        coverages = plan.get("coverage") or []
        coverage_names = []
        benefit_names = []
        for c in coverages:
            c_type = c.get("type", {})
            c_name = c_type.get("text") or (c_type.get("coding") or [{}])[0].get("display")
            if c_name and c_name not in coverage_names:
                coverage_names.append(c_name)
            for b in (c.get("benefit") or []):
                b_type = b.get("type", {})
                b_name = b_type.get("text") or (b_type.get("coding") or [{}])[0].get("display")
                if b_name and b_name not in benefit_names:
                    benefit_names.append(b_name)

        plans = plan.get("plan") or []
        plan_names = []
        for p in plans:
            p_type = p.get("type", {})
            p_name = p_type.get("text") or (p_type.get("coding") or [{}])[0].get("display")
            if p_name and p_name not in plan_names:
                plan_names.append(p_name)

        exclusions = [
            ext for ext in (plan.get("extension") or [])
            if "Exclusion" in ext.get("url", "") or "exclusion" in ext.get("url", "")
        ]
        exclusion_names = []
        for e in exclusions:
            category = e.get("extension", [{}])[0]
            val_concept = category.get("valueCodeableConcept", {})
            e_name = val_concept.get("text") or (val_concept.get("coding") or [{}])[0].get("display")
            if e_name and e_name not in exclusion_names:
                exclusion_names.append(e_name)

        summary = {
            "planName": plan.get("name", "N/A"),
            "alias": plan.get("alias", []),
            "status": plan.get("status", "unknown"),
            "language": plan.get("language", "N/A"),
            "planType": plan_type_coding.get("display", plan_type_coding.get("code", "N/A")),
            "period": {"start": period.get("start", "N/A"), "end": period.get("end", "N/A")},
            "insurer": insurer.get("name", "N/A"),
            "tpa": tpa.get("name") if tpa else None,
            "networks": [n.get("display", "") for n in (plan.get("network") or [])],
            "coverageCount": len(coverages),
            "benefitCount": sum(len(c.get("benefit") or []) for c in coverages),
            "planCount": len(plans),
            "exclusionCount": len(exclusions),
            "totalResources": len(entries),
            "coverageNames": coverage_names,
            "benefitNames": benefit_names,
            "planNames": plan_names,
            "exclusionNames": exclusion_names,
        }

        return JSONResponse(content=summary, status_code=200)

    except Exception as e:
        logger.exception(constants.LOG_CLAIM_BUNDLE_SUMMARY_ERROR)
        return JSONResponse(content={"error": {"code": constants.ERROR_CODE_SUMMARY_ERROR, "message": str(e)}}, status_code=400)
