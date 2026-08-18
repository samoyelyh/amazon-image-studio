import { describe, expect, it } from 'vitest'
import type { ServerJob } from './jobsApi'
import {
  batchStyleProfileSnapshot,
  batchStyleProfileDisplay,
  buildStructureConsistencyPrompt,
  parseConsistencyDecisions,
  parseProfileFromJob,
  restoreWorkflowStyleProfile,
} from './batchTryOnStyleProfile'

function jobWithText(text: string): ServerJob {
  return { result_json: { metadata: { text } } } as unknown as ServerJob
}

describe('batch try-on style profile', () => {
  it('keeps stable structure but excludes first-sample variable visual details', () => {
    const profile = parseProfileFromJob(jobWithText(JSON.stringify({
      batch_style_profile: {
        category: 'football_jersey',
        garment_structure: { neckline: 'v_neck', sleeve_type: 'short_sleeve', fit: 'cropped' },
        view_rules: { front_back_must_not_swap: true },
        design_rules: { preserve_text: true, preserve_numbers: true, preserve_font_style: true },
        structure_rules: { preserve_neckline: true, preserve_sleeves: true },
        main_color: 'black',
        specific_number: '99',
      },
      first_sample_observation: { main_color: 'black', specific_number: '99' },
    })), {
      profileKey: 'profile-1', sourceSampleAssetId: 'asset-1', sourceGarmentId: 'garment-1', analysisModel: 'gpt-test',
    })

    const snapshot = batchStyleProfileSnapshot(profile)
    expect(snapshot.garment_structure).toMatchObject({ neckline: 'v_neck', sleeve_type: 'short_sleeve', fit: 'cropped' })
    expect(JSON.stringify(snapshot)).not.toContain('black')
    expect(JSON.stringify(snapshot)).not.toContain('99')
    expect(profile.firstSampleObservation).toMatchObject({ main_color: 'black', specific_number: '99' })
  })

  it('builds a lightweight structure-only comparison prompt', () => {
    const prompt = buildStructureConsistencyPrompt(3)
    expect(prompt).toContain('Ignore color, text, numbers, names, logos and graphic content')
    expect(prompt).toContain('Return 3 decisions')
  })

  it('fails closed when a consistency decision is missing', () => {
    const decisions = parseConsistencyDecisions(jobWithText(JSON.stringify({
      decisions: [{ candidate_index: 1, same_structure_family: true }],
    })), 2)
    expect(decisions).toEqual([
      { candidateIndex: 1, sameStructureFamily: true, reason: undefined },
      { candidateIndex: 2, sameStructureFamily: false, reason: 'The structure check did not return a valid decision.' },
    ])
  })

  it('restores a concrete workflow analysis before the image batch is ready', () => {
    const profile = restoreWorkflowStyleProfile({
      profile_key: 'first-garment-structure',
      source_sample_asset_id: 'asset-1',
      category: 'sports_jersey',
      garment_structure: {
        neckline: 'v_neck', sleeve_type: 'short_sleeve', fit: 'regular', closure: 'pullover', hem_type: 'straight',
      },
      view_rules: { supports_front: true, supports_back: true, front_back_must_not_swap: true },
      design_rules: { preserve_text: true, preserve_numbers: true },
      structure_rules: { preserve_neckline: true, preserve_sleeves: true },
      analysis_model: 'gpt-test',
      analysis_version: 'server-first-garment-v1',
      observation: { summary: 'visible structure' },
    }, [{
      id: 'garment-1', batchId: 'batch-1', garmentImageId: 'image-1', serverAssetId: 'asset-1',
      garmentFileName: 'shirt.png', index: 0, selected: true, createdAt: 1,
    }])
    expect(profile.sourceGarmentId).toBe('garment-1')
    expect(profile.coveredGarmentIds).toEqual(['garment-1'])
    expect(profile.garmentStructure).toMatchObject({
      neckline: 'v_neck', sleeveType: 'short_sleeve', fit: 'regular', closure: 'pullover', hemType: 'straight',
    })
  })

  it('builds a readable structured result for the workspace panel', () => {
    const profile = parseProfileFromJob(jobWithText(JSON.stringify({
      batch_style_profile: {
        category: 'football_jersey',
        garment_structure: { neckline: 'v_neck', sleeve_type: 'short_sleeve', fit: 'cropped' },
        view_rules: { supports_front: true, supports_back: true, front_back_must_not_swap: true },
        design_rules: { preserve_text: true, preserve_numbers: true, preserve_graphics: true },
        structure_rules: { preserve_neckline: true, preserve_sleeves: true },
      },
    })), {
      profileKey: 'profile-ui', sourceSampleAssetId: 'asset-1', sourceGarmentId: 'garment-1', analysisModel: 'gpt-test',
    })
    const display = batchStyleProfileDisplay(profile)
    expect(display.category).toBe('橄榄球衣')
    expect(display.structure).toContainEqual({ label: '领型', value: 'V 领' })
    expect(display.structure).toContainEqual({ label: '袖型', value: '短袖' })
    expect(display.viewRules).toContain('正反面不可互换')
    expect(display.preservationRules).toContain('保持文字')
    expect(display.preservationRules).toContain('保持领型')
  })
})
