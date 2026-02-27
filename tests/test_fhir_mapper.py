"""
Tests for InsurancePlanFHIRMapper — validates that the FHIR R4B bundle
is built correctly with all expected parameters.
"""
import unittest

from src.services.fhir.InsurancePlanFHIRMapper import InsurancePlanFHIRMapper


FIXTURE: dict = {
    "organisation": {
        "name": "Test Health Insurance Co.",
        "phone": "+91-1800-123-4567",
        "email": "care@testhealthins.com",
        "website": "https://www.testhealthins.com",
    },
    "tpaOrganisation": {
        "name": "Speedy TPA Pvt Ltd",
        "identifier": "IRDAI/TPA/2024/001",
    },
    "insurancePlan": {
        "status": "active",
        "name": "Test Comprehensive Health Plan",
        "alias": ["TestHealth Pro", "THP-500"],
        "language": "en-IN",
        "typeCode": "01",
        "typeDisplay": "Hospitalisation Indemnity",
        "periodStart": "2024-04-01",
        "periodEnd": "2025-03-31",
        "coverageArea": ["India", "Pan India"],
        "networks": ["TestHealth Network Hospitals", "PartnerCare PPN"],
        "contacts": [
            {
                "purpose": "Claims Helpline",
                "name": "Claims Team",
                "phone": "+91-1800-999-0000",
                "email": "claims@testhealthins.com",
            }
        ],
        "supportingInfoRequirements": [
            {
                "categoryCode": "POI",
                "categoryDisplay": "Proof of Identity",
                "documentCode": "ADN",
                "documentDisplay": "Aadhaar Card",
            }
        ],
        "exclusions": [
            {
                "categoryCode": "Excl01",
                "categoryDisplay": "Pre-Existing Diseases",
                "statement": "Pre-existing conditions are excluded for the first 48 months.",
            }
        ],
        "coverages": [
            {
                "typeDisplay": "Inpatient Care",
                "condition": "Subject to sum insured",
                "benefits": [
                    {
                        "typeCode": "",
                        "typeDisplay": "Room Rent",
                        "limitValue": "5000",
                        "limitUnit": "INR",
                    }
                ],
            }
        ],
        "plans": [
            {
                "planTypeCode": "01",
                "planTypeDisplay": "Individual",
                "specificCosts": [
                    {
                        "categoryCode": "49122002",
                        "categoryDisplay": "Ambulance",
                        "benefitTypeCode": "49122002",
                        "benefitTypeDisplay": "Ambulance Service",
                        "costType": "fullcoverage",
                        "costValue": "2000",
                        "costUnit": "INR",
                    }
                ],
            }
        ],
    },
}


def _get_resources(bundle_dict: dict) -> dict:
    """Return a map of resourceType -> resource dict for quick lookup."""
    resources: dict = {}
    for entry in bundle_dict.get("entry", []):
        resource = entry.get("resource", {})
        rt = resource.get("resourceType", "Unknown")
        resources.setdefault(rt, []).append(resource)
    return resources


class TestBundleTopLevel(unittest.TestCase):
    def setUp(self):
        self.bundle = InsurancePlanFHIRMapper(FIXTURE).generate_dict()

    def test_resource_type(self):
        self.assertEqual(self.bundle["resourceType"], "Bundle")

    def test_bundle_type_collection(self):
        self.assertEqual(self.bundle["type"], "collection")

    def test_bundle_language(self):
        self.assertEqual(self.bundle.get("language"), "en-IN")

    def test_bundle_has_entries(self):
        self.assertGreater(len(self.bundle.get("entry", [])), 0)


class TestOrganizationResource(unittest.TestCase):
    def setUp(self):
        bundle = InsurancePlanFHIRMapper(FIXTURE).generate_dict()
        self.resources = _get_resources(bundle)
        self.orgs = self.resources.get("Organization", [])

    def test_at_least_two_orgs(self):
        # Insurer + TPA + 2 networks = 4 total
        self.assertGreaterEqual(len(self.orgs), 2)

    def test_insurer_org_name(self):
        names = [o.get("name") for o in self.orgs]
        self.assertIn("Test Health Insurance Co.", names)

    def test_org_has_meta_profile(self):
        insurer = next(o for o in self.orgs if o.get("name") == "Test Health Insurance Co.")
        meta = insurer.get("meta", {})
        self.assertIn("profile", meta)
        self.assertTrue(len(meta["profile"]) > 0)

    def test_org_identifier_use_official(self):
        insurer = next(o for o in self.orgs if o.get("name") == "Test Health Insurance Co.")
        identifiers = insurer.get("identifier", [])
        self.assertTrue(len(identifiers) > 0)
        self.assertEqual(identifiers[0].get("use"), "official")

    def test_org_telecom_has_email(self):
        insurer = next(o for o in self.orgs if o.get("name") == "Test Health Insurance Co.")
        systems = [t.get("system") for t in insurer.get("telecom", [])]
        self.assertIn("email", systems)

    def test_org_telecom_has_url(self):
        insurer = next(o for o in self.orgs if o.get("name") == "Test Health Insurance Co.")
        systems = [t.get("system") for t in insurer.get("telecom", [])]
        self.assertIn("url", systems)

    def test_network_orgs_present(self):
        names = [o.get("name") for o in self.orgs]
        self.assertIn("TestHealth Network Hospitals", names)
        self.assertIn("PartnerCare PPN", names)


class TestInsurancePlanResource(unittest.TestCase):
    def setUp(self):
        bundle = InsurancePlanFHIRMapper(FIXTURE).generate_dict()
        resources = _get_resources(bundle)
        plans = resources.get("InsurancePlan", [])
        self.assertGreater(len(plans), 0, "No InsurancePlan found in bundle")
        self.plan = plans[0]

    def test_has_meta_profile(self):
        meta = self.plan.get("meta", {})
        self.assertIn("profile", meta)

    def test_has_narrative_text(self):
        text = self.plan.get("text", {})
        self.assertEqual(text.get("status"), "generated")
        self.assertIn("<div", text.get("div", ""))

    def test_language(self):
        self.assertEqual(self.plan.get("language"), "en-IN")

    def test_alias(self):
        aliases = self.plan.get("alias", [])
        self.assertIn("TestHealth Pro", aliases)
        self.assertIn("THP-500", aliases)

    def test_network_references(self):
        networks = self.plan.get("network", [])
        self.assertGreaterEqual(len(networks), 2)
        displays = [n.get("display") for n in networks]
        self.assertIn("TestHealth Network Hospitals", displays)

    def test_identifier_official(self):
        identifiers = self.plan.get("identifier", [])
        self.assertTrue(len(identifiers) > 0)
        self.assertEqual(identifiers[0].get("use"), "official")

    def test_contact_has_name(self):
        contacts = self.plan.get("contact", [])
        self.assertTrue(len(contacts) > 0)
        name = contacts[0].get("name", {})
        self.assertEqual(name.get("text"), "Claims Team")

    def test_contact_has_email_telecom(self):
        contacts = self.plan.get("contact", [])
        systems = [t.get("system") for t in contacts[0].get("telecom", [])]
        self.assertIn("email", systems)

    def test_coverage_benefit_limit_code(self):
        coverages = self.plan.get("coverage", [])
        self.assertTrue(len(coverages) > 0)
        benefits = coverages[0].get("benefit", [])
        self.assertTrue(len(benefits) > 0)
        limits = benefits[0].get("limit", [])
        self.assertTrue(len(limits) > 0)
        self.assertIn("code", limits[0])

    def test_specific_cost_applicability(self):
        plans = self.plan.get("plan", [])
        self.assertTrue(len(plans) > 0)
        specific_costs = plans[0].get("specificCost", [])
        self.assertTrue(len(specific_costs) > 0)
        benefit_costs = specific_costs[0].get("benefit", [])[0].get("cost", [])
        self.assertTrue(len(benefit_costs) > 0)
        self.assertIn("applicability", benefit_costs[0])

    def test_plan_has_identifier(self):
        plans = self.plan.get("plan", [])
        self.assertTrue(len(plans) > 0)
        identifiers = plans[0].get("identifier", [])
        self.assertTrue(len(identifiers) > 0)


if __name__ == "__main__":
    unittest.main()
