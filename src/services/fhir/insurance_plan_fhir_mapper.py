import uuid
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from fhir.resources.bundle import Bundle, BundleEntry
from fhir.resources.codeableconcept import CodeableConcept
from fhir.resources.coding import Coding
from fhir.resources.contactpoint import ContactPoint
from fhir.resources.composition import Composition, CompositionSection
from fhir.resources.extension import Extension
from fhir.resources.extendedcontactdetail import ExtendedContactDetail
from fhir.resources.humanname import HumanName
from fhir.resources.identifier import Identifier
from fhir.resources.meta import Meta
from fhir.resources.narrative import Narrative
from fhir.resources.period import Period
from fhir.resources.quantity import Quantity
from fhir.resources.reference import Reference
from fhir.resources.organization import Organization
from fhir.resources.insuranceplan import (
    InsurancePlan,
    InsurancePlanCoverage,
    InsurancePlanCoverageBenefit,
    InsurancePlanCoverageBenefitLimit,
    InsurancePlanPlan,
    InsurancePlanPlanSpecificCost,
    InsurancePlanPlanSpecificCostBenefit,
    InsurancePlanPlanSpecificCostBenefitCost,
)
from fhir.resources.organization import Organization
from pydantic import ValidationError

from src.services.fhir import fhir_constants as fhir_const
from src import constants
import os
import json

logger = logging.getLogger(__name__)

from src.config import ROOT_DIR

SNOMED_DICT_PATH = os.path.join(ROOT_DIR, "src", "core", "snomed_dictionary.json")
SNOMED_DICT = {}
TERM_TO_CODE = {}
try:
    with open(SNOMED_DICT_PATH, "r") as f:
        SNOMED_DICT = json.load(f)
        TERM_TO_CODE = SNOMED_DICT.get("termToCodeMapping", {})
except FileNotFoundError:
    logger.warning(constants.LOG_FHIR_SNOMED_NOT_FOUND)


def _make_coding(
    code: Optional[str] = None,
    display: Optional[str] = None,
    system: Optional[str] = None,
) -> Coding:
    kwargs: Dict[str, Any] = {}
    if system:
        kwargs["system"] = system
    if code:
        kwargs["code"] = code
    if display:
        kwargs["display"] = display
    return Coding(**kwargs)


def _make_concept(
    code: Optional[str] = None,
    display: Optional[str] = None,
    system: Optional[str] = None,
    text: Optional[str] = None,
) -> CodeableConcept:
    kwargs: Dict[str, Any] = {}
    actual_text = text or display
    if actual_text:
        kwargs["text"] = actual_text

    if code or system:
        c_code = code or "UNK"
        c_system = system or "http://terminology.hl7.org/CodeSystem/v3-NullFlavor"
        c_display = display
        if c_code == "UNK":
            c_display = "unknown"
            
        kwargs["coding"] = [_make_coding(code=c_code, display=c_display, system=c_system)]
        
    return CodeableConcept(**kwargs)


def _make_narrative(text_summary: str, status: str = "generated") -> Narrative:
    safe = text_summary.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    div = f'<div xmlns="http://www.w3.org/1999/xhtml" lang="en" xml:lang="en"><p>{safe}</p></div>'
    return Narrative(status=status, div=div)


class InsurancePlanFHIRMapper:

    def __init__(self, extracted_data: Dict[str, Any]):
        self.data: Dict[str, Any] = extracted_data or {}
        bundle_uuid = str(uuid.uuid4())
        self.bundle = Bundle(
            id=bundle_uuid,
            identifier=Identifier(
                system=fhir_const.SYS_IDENTIFIER,
                value=bundle_uuid
            ),
            meta=Meta(
                versionId="1",
                profile=[fhir_const.META_PROFILE_INSURANCE_PLAN_BUNDLE]
            ),
            type="collection",
            language=fhir_const.LANGUAGE_EN_IN,
            timestamp=datetime.now(timezone.utc),
            entry=[],
        )

    def _add_to_bundle(self, resource) -> None:
        entry = BundleEntry(
            fullUrl=f"urn:uuid:{resource.id}",
            resource=resource,
        )
        if self.bundle.entry is None:
            self.bundle.entry = []
        self.bundle.entry.append(entry)

    def _get(self, data: Dict[str, Any], key: str, fallback: Any = None) -> Any:
        value = data.get(key)
        if value is None or str(value).strip() == "":
            return fallback
        return value

    def _require(self, data: Dict[str, Any], key: str, context: str, fallback: str = "UNK") -> Any:
        value = self._get(data, key)
        if value is None:
            logger.warning(constants.LOG_FHIR_MISSING_REQUIRED_FIELD, key, context, fallback)
            return fallback
        return value

    def _parse_float(self, value: Any, default: float = 0.0) -> float:
        try:
            return float(value)
        except (ValueError, TypeError):
            logger.warning(constants.LOG_FHIR_FLOAT_PARSE_FAILED.format(value=value, default=default))
            return default

    def _lookup_snomed_concept(self, provided_code: Optional[str], display_text: Optional[str]) -> Tuple[Optional[str], Optional[str]]:
        s_code = str(provided_code).strip() if provided_code else ""
        s_display = str(display_text).strip().lower() if display_text else ""
        
        if s_code:
            official_display = SNOMED_DICT.get("benefitType", {}).get(s_code)
            if official_display:
                return s_code, official_display

        if s_display and s_display in TERM_TO_CODE:
            mapped_code = TERM_TO_CODE[s_display]
            official_display = SNOMED_DICT.get("benefitType", {}).get(mapped_code)
            if official_display:
                return mapped_code, official_display
            return mapped_code, display_text
            

        return provided_code, display_text

    def _build_organization(
        self,
        org_data: Optional[Dict[str, Any]],
        is_tpa: bool = False,
    ) -> Optional[str]:
        if not org_data:
            return None
        try:
            org_id = str(uuid.uuid4())
            org_name = self._require(org_data, "name", "organisation")
            org = Organization(
                id=org_id,
                meta=Meta(profile=[fhir_const.META_PROFILE_ORGANIZATION]),
                text=_make_narrative(f"Organisation: {org_name}"),
                name=org_name,
            )

            identifier_value = self._get(org_data, "identifier")
            id_system = fhir_const.SYS_IRDAI_IDENTIFIER if is_tpa else fhir_const.SYS_INSURER_IDENTIFIER
            identifiers = []
            if identifier_value:
                identifiers.append(
                    Identifier(
                        type=_make_concept(code="PRN", display="Provider number", system="http://terminology.hl7.org/CodeSystem/v2-0203"),
                        use=fhir_const.IDENTIFIER_USE_OFFICIAL,
                        system=id_system,
                        value=str(identifier_value).strip(),
                    )
                )
            else:
                identifiers.append(
                    Identifier(
                        type=_make_concept(code="PRN", display="Provider number", system="http://terminology.hl7.org/CodeSystem/v2-0203"),
                        use=fhir_const.IDENTIFIER_USE_OFFICIAL,
                        system=id_system,
                        value=org_name,
                    )
                )
            org.identifier = identifiers

            telecom_entries: List[ContactPoint] = []
            phone = self._get(org_data, "phone")
            if phone:
                telecom_entries.append(ContactPoint(system=fhir_const.TELECOM_SYSTEM_PHONE, value=str(phone).strip()))
            email = self._get(org_data, "email")
            if email:
                telecom_entries.append(ContactPoint(system=fhir_const.TELECOM_SYSTEM_EMAIL, value=str(email).strip()))
            website = self._get(org_data, "website")
            if website:
                telecom_entries.append(ContactPoint(system=fhir_const.TELECOM_SYSTEM_URL, value=str(website).strip()))
            if telecom_entries:
                org.contact = [ExtendedContactDetail(telecom=telecom_entries)]

            self._add_to_bundle(org)
            return f"urn:uuid:{org_id}"

        except ValidationError as e:
            ctx = constants.FHIR_ORG_CONTEXT_TPA if is_tpa else constants.FHIR_ORG_CONTEXT_INSURER
            logger.error(constants.LOG_FHIR_SKIP_ORG_VALIDATION, ctx, e)
            return None

    def _build_networks(self, networks_data: List[str]) -> List[Reference]:
        refs: List[Reference] = []
        for network_name in (networks_data or []):
            if not network_name or not str(network_name).strip():
                continue
            net_id = str(uuid.uuid4())
            network_name_str = str(network_name).strip()
            network_org = Organization(
                id=net_id,
                meta=Meta(profile=[fhir_const.META_PROFILE_ORGANIZATION]),
                text=_make_narrative(f"Network: {network_name_str}"),
                name=network_name_str,
                type=[_make_concept(
                    code="prov",
                    display="Healthcare Provider",
                    system="http://terminology.hl7.org/CodeSystem/organization-type",
                )],
                identifier=[
                    Identifier(
                        type=_make_concept(code="PRN", display="Provider number", system="http://terminology.hl7.org/CodeSystem/v2-0203"),
                        use=fhir_const.IDENTIFIER_USE_OFFICIAL,
                        system=fhir_const.SYS_IDENTIFIER,
                        value=network_name_str,
                    )
                ],
            )
            self._add_to_bundle(network_org)
            refs.append(Reference(reference=f"urn:uuid:{net_id}", display=str(network_name).strip()))
        return refs

    def _build_complex_extension(self, url: str, sub_extensions: List[Extension]) -> Extension:
        return Extension(url=url, extension=sub_extensions)

    def _build_contacts(self, contacts_data: List[Dict[str, Any]]) -> List[ExtendedContactDetail]:
        contacts: List[ExtendedContactDetail] = []
        for cd in (contacts_data or []):
            kwargs: Dict[str, Any] = {}
            purpose_text = self._get(cd, "purpose")
            if purpose_text:
                kwargs["purpose"] = _make_concept(
                    code="PATINF",
                    display="Patient",
                    system=fhir_const.CONTACT_PURPOSE_SYSTEM,
                    text=purpose_text,
                )
            contact_name = self._get(cd, "name")
            if contact_name:
                kwargs["name"] = [HumanName(text=str(contact_name))]
            telecom_entries: List[ContactPoint] = []
            phone = self._get(cd, "phone")
            if phone:
                telecom_entries.append(ContactPoint(system=fhir_const.TELECOM_SYSTEM_PHONE, value=str(phone)))
            email = self._get(cd, "email")
            if email:
                telecom_entries.append(ContactPoint(system=fhir_const.TELECOM_SYSTEM_EMAIL, value=str(email)))
            if telecom_entries:
                kwargs["telecom"] = telecom_entries
            if kwargs:
                contacts.append(ExtendedContactDetail(**kwargs))
        return contacts

    def _build_coverage_areas(self, areas_data: List[str]) -> List[Reference]:
        return [Reference(display=area) for area in (areas_data or []) if area]

    def _build_plan_extensions(self, plan_data: Dict[str, Any]) -> List[Extension]:
        extensions: List[Extension] = []
        return extensions

    def _build_benefit_block(self, ben_data: Dict[str, Any]) -> InsurancePlanCoverageBenefit:
        raw_code = self._get(ben_data, "typeCode")
        display_text = self._get(ben_data, "typeDisplay")
        final_code, final_display = self._lookup_snomed_concept(raw_code, display_text)
        system = fhir_const.SYS_SNOMED if (final_code and str(final_code).isdigit()) else None

        benefit = InsurancePlanCoverageBenefit(
            type=_make_concept(code=final_code, display=final_display, system=system)
        )

        limit_value = self._get(ben_data, "limitValue")
        if limit_value is not None:
            limit_unit = self._get(ben_data, "limitUnit")
            safe_value = self._parse_float(limit_value)
            limit_quantity = Quantity(value=safe_value, unit=limit_unit)
            limit_code = InsurancePlanCoverageBenefitLimit(
                value=limit_quantity,
                code=_make_concept(text=f"{limit_value} {limit_unit or ''}".strip())
            )
            benefit.limit = [limit_code]

        return benefit

    def _build_coverages(self, coverages_data: List[Dict[str, Any]]) -> List[InsurancePlanCoverage]:
        coverages: List[InsurancePlanCoverage] = []
        for cov_data in (coverages_data or []):
            benefits = [
                self._build_benefit_block(ben)
                for ben in (cov_data.get("benefits") or [])
            ]
            if not benefits:
                continue
                
            coverage = InsurancePlanCoverage(
                type=_make_concept(text=self._get(cov_data, "typeDisplay") or "Coverage"),
                benefit=benefits,
            )

            coverages.append(coverage)
        return coverages

    def _build_specific_cost_block(self, cost_data: Dict[str, Any]) -> Optional[InsurancePlanPlanSpecificCost]:
        try:
            cost_value_raw = self._require(cost_data, "costValue", "specificCost.cost")
            cost_type_code = self._require(cost_data, "costType", "specificCost.cost")
            cost_unit = self._require(cost_data, "costUnit", "specificCost.cost")

            applicability_map = {
                "copay": fhir_const.APPLICABILITY_IN_NETWORK,
                "deductible": fhir_const.APPLICABILITY_IN_NETWORK,
                "fullcoverage": fhir_const.APPLICABILITY_IN_NETWORK,
                "out-of-network": fhir_const.APPLICABILITY_OUT_OF_NETWORK,
            }
            applicability_code = applicability_map.get(
                str(cost_type_code).lower(), fhir_const.APPLICABILITY_OTHER
            )

            benefit_cost = InsurancePlanPlanSpecificCostBenefitCost(
                type=_make_concept(
                    text=str(cost_type_code).capitalize(),
                ),
                applicability=_make_concept(
                    code=applicability_code,
                    display=str(applicability_code).replace("-", " ").title() if applicability_code else "Other",
                    system="http://terminology.hl7.org/CodeSystem/applicability",
                ),
                value=Quantity(value=self._parse_float(cost_value_raw), unit=cost_unit),
            )

            raw_ben_code = self._require(cost_data, "benefitTypeCode", "specificCost.benefit")
            display_ben_text = self._get(cost_data, "benefitTypeDisplay")
            final_ben_code, final_ben_display = self._lookup_snomed_concept(raw_ben_code, display_ben_text)
            sys_ben = fhir_const.SYS_SNOMED if (final_ben_code and str(final_ben_code).isdigit()) else None

            benefit = InsurancePlanPlanSpecificCostBenefit(
                type=_make_concept(code=final_ben_code, display=final_ben_display, system=sys_ben),
                cost=[benefit_cost],
            )

            raw_cat_code = self._require(cost_data, "categoryCode", "specificCost")
            display_cat_text = self._get(cost_data, "categoryDisplay")
            final_cat_code, final_cat_display = self._lookup_snomed_concept(raw_cat_code, display_cat_text)
            sys_cat = fhir_const.SYS_SNOMED if (final_cat_code and str(final_cat_code).isdigit()) else None

            return InsurancePlanPlanSpecificCost(
                category=_make_concept(code=final_cat_code, display=final_cat_display, system=sys_cat),
                benefit=[benefit],
            )

        except (ValidationError, ValueError, TypeError) as e:
            logger.warning(constants.LOG_FHIR_SKIP_COST_BLOCK, e)
            return None

    def _build_financial_plans(self, plans_data: List[Dict[str, Any]]) -> List[InsurancePlanPlan]:
        plans: List[InsurancePlanPlan] = []
        for plan_data in (plans_data or []):
            plan = InsurancePlanPlan(
                identifier=[
                    Identifier(
                        use=fhir_const.IDENTIFIER_USE_OFFICIAL,
                        system=fhir_const.SYS_IDENTIFIER,
                        value=f"urn:uuid:{uuid.uuid4()}",
                    )
                ],
                type=_make_concept(
                    code=self._get(plan_data, "planTypeCode"),
                    display=self._get(plan_data, "planTypeDisplay"),
                    system=fhir_const.VS_PLAN_TYPE,
                ),
            )
            specific_costs = [
                cost_block
                for cost_data in (plan_data.get("specificCosts") or [])
                if (cost_block := self._build_specific_cost_block(cost_data)) is not None
            ]
            if specific_costs:
                plan.specificCost = specific_costs
            plans.append(plan)
        return plans

    def _build_insurance_plan(
        self,
        plan_data: Optional[Dict[str, Any]],
        owned_by_ref: str,
        admin_by_ref: Optional[str] = None,
        network_refs: Optional[List[Reference]] = None,
    ) -> None:
        if not plan_data:
            return
        try:
            plan_id = str(uuid.uuid4())
            plan_name = self._require(plan_data, "name", "insurancePlan")

            insurance_plan = InsurancePlan(
                id=plan_id,
                meta=Meta(profile=[fhir_const.META_PROFILE_INSURANCE_PLAN]),
                text=_make_narrative(
                    f"Insurance Plan: {plan_name}. "
                    f"Status: {plan_data.get('status', 'active')}."
                ),
                language="en",
                status=self._get(plan_data, "status", "active"),
                name=plan_name,
                alias=[a for a in (plan_data.get("alias") or []) if a],
                identifier=[
                    Identifier(
                        use=fhir_const.IDENTIFIER_USE_OFFICIAL,
                        system=fhir_const.SYS_IDENTIFIER,
                        value=f"urn:uuid:{uuid.uuid4()}",
                    )
                ],
                type=[
                    _make_concept(
                        code=self._require(plan_data, "typeCode", "insurancePlan.type"),
                        display=self._get(plan_data, "typeDisplay"),
                        system=fhir_const.VS_INSURANCE_PLAN_TYPE,
                    )
                ],
                ownedBy=Reference(reference=owned_by_ref),
            )

            if admin_by_ref:
                insurance_plan.administeredBy = Reference(reference=admin_by_ref)

            period_start = self._get(plan_data, "periodStart") or "2020-01-01"
            period_end = self._get(plan_data, "periodEnd")
            insurance_plan.period = Period(start=period_start, end=period_end)

            if network_refs:
                insurance_plan.network = network_refs

            contacts = self._build_contacts(plan_data.get("contacts") or [])
            if contacts:
                insurance_plan.contact = contacts

            coverage_areas = self._build_coverage_areas(plan_data.get("coverageArea") or [])
            if coverage_areas:
                insurance_plan.coverageArea = coverage_areas

            extensions = self._build_plan_extensions(plan_data)
            if extensions:
                insurance_plan.extension = extensions

            coverages = self._build_coverages(plan_data.get("coverages") or [])
            if coverages:
                insurance_plan.coverage = coverages

            plans = self._build_financial_plans(plan_data.get("plans") or [])
            if plans:
                insurance_plan.plan = plans

            self._add_to_bundle(insurance_plan)

        except ValidationError as e:
            logger.error(constants.LOG_FHIR_SKIP_INSURANCE_PLAN, e)

    def generate_dict(self) -> Dict[str, Any]:
        org_data = self.data.get("organisation") or self.data.get("organization") or {}
        owned_by_ref = self._build_organization(org_data)
        admin_by_ref = self._build_organization(self.data.get("tpaOrganisation"), is_tpa=True)

        plan_data = self.data.get("insurancePlan") or {}
        network_refs = self._build_networks(plan_data.get("networks") or [])

        if owned_by_ref:
            self._build_insurance_plan(plan_data, owned_by_ref, admin_by_ref, network_refs)
        else:
            logger.error(constants.LOG_FHIR_OWNED_BY_NONE)

        if self.bundle.entry:
            # Ensure InsurancePlan is the first entry
            self.bundle.entry.sort(key=lambda e: 0 if getattr(e.resource, "__resource_type__", None) == "InsurancePlan" else 1)

        out_dict = self.bundle.model_dump(mode="json", exclude_none=True)
        
        # Post-process for FHIR R4 validator compliance (ExtendedContactDetail.name in fhir.resources is array, R4 validator expects object)
        for entry in out_dict.get("entry", []):
            res = entry.get("resource", {})
            if res.get("resourceType") in ["InsurancePlan", "Organization"]:
                for contact in res.get("contact", []):
                    if "name" in contact and isinstance(contact["name"], list) and len(contact["name"]) > 0:
                        contact["name"] = contact["name"][0]

        return out_dict
