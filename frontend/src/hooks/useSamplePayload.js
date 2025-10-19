import { useCallback } from 'react';
import dayjs from 'dayjs';

export function buildSamplePayload({
  holderDid = 'did:example:patient-001',
  conditionCode = 'K29.7',
  managingOrg = 'org:tph-001',
}) {
  return {
    fhir_profile: 'https://profiles.iisigroup.com.tw/StructureDefinition/medssi-bundle',
    condition: {
      resourceType: 'Condition',
      id: `cond-${holderDid.split(':').pop()}`,
      code: {
        coding: [
          {
            system: 'http://hl7.org/fhir/sid/icd-10',
            code: conditionCode,
            display: 'Gastritis, unspecified',
          },
        ],
        text: 'Gastritis, unspecified',
      },
      recordedDate: dayjs().format('YYYY-MM-DD'),
      encounter: {
        system: 'urn:medssi:encounter-id',
        value: `enc-${holderDid.split(':').pop()}`,
      },
      subject: {
        system: 'did:example',
        value: holderDid,
      },
    },
    encounter_summary_hash: 'urn:sha256:3a1f0c98c5d4a4efed2d4dfe58e8',
    managing_organization: {
      system: 'urn:medssi:org',
      value: managingOrg,
    },
    issued_on: dayjs().format('YYYY-MM-DD'),
    consent_expires_on: dayjs().add(60, 'day').format('YYYY-MM-DD'),
    medication_dispense: [
      {
        resourceType: 'MedicationDispense',
        id: `med-${holderDid.split(':').pop()}`,
        medicationCodeableConcept: {
          coding: [
            {
              system: 'http://www.whocc.no/atc',
              code: 'A02BC05',
              display: 'Omeprazole 20mg',
            },
          ],
          text: 'Omeprazole 20mg',
        },
        quantity_text: '30 capsules',
        days_supply: 30,
        performer: {
          system: 'did:example',
          value: 'did:example:rx-unit-01',
        },
        pickup_window_end: dayjs().add(7, 'day').format('YYYY-MM-DD'),
      },
    ],
  };
}

export function useSamplePayload(holderDid) {
  return useCallback(() => buildSamplePayload({ holderDid }), [holderDid]);
}
