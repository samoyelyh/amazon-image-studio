import { describe, expect, it } from 'vitest'
import type { JobOutput } from '../../lib/jobsApi'
import type { ListingImageTask, ListingImageTaskGroup } from '../../lib/listingWorkflowApi'
import { deriveAttachmentResultData } from './AttachmentResultReviewPanel'

function output(id: string, discarded = false): JobOutput {
  return {
    id, asset_id: `asset-${id}`, filename: `${id}.png`, display_filename: `${id}.png`, download_filename: `${id}.png`,
    download_url: `/assets/${id}`, mime_type: 'image/png', width: 1024, height: 1024, size: 10,
    sequence_number: 0, url: `/images/${id}`, url_expires_at: null,
    review_status: 'approved', review_state_version: 1, reviewed_at: null,
    discarded_at: discarded ? '2026-08-19T10:00:00Z' : null, is_final: id === 'old-final',
  }
}

function task(id: string, slot: number, result: JobOutput): ListingImageTask {
  return {
    id, batch_id: `batch-${id}`, image_type: 'gift_scene', prompt_status: 'submitted', status: 'succeeded', progress: 100,
    final_prompt: 'prompt snapshot', model_code: 'image-2', error_code: null, error_message: null,
    created_at: `2026-08-19T0${slot}:00:00Z`, started_at: null, finished_at: null, input_assets: [], outputs: [result],
    variation_type_code: null, variation_type_name: null, variation_plan_code: null, variation_plan_name: null,
    variation_version: null, chinese_prompt: '', slot_index: slot, generation_mode: 'standard', requested_aspect_ratio: '1:1',
    requested_width: 1024, requested_height: 1024, plan_version_id: 'plan', prompt_version_id: 'prompt', reference_understanding_id: 'ref',
  }
}

function group(id: string, number: number, tasks: ListingImageTask[]): ListingImageTaskGroup {
  return {
    id, batch_id: `batch-${id}`, listing_image_project_id: 'project', session_id: 'session', listing_version_id: 'version',
    listing_version_number: 1, category_skill_version_id: null, skill_version_number: 1, category_name: '', skill_name: '', listing_summary: {
      title: { en: '', zh: '' }, bullet_points: [], description: { en: '', zh: '' }, search_terms: { en: [], zh: [] },
      selling_points: { en: '', zh: '' }, usage_scenarios: { en: '', zh: '' }, customization_notes: { en: '', zh: '' }, cautions: { en: '', zh: '' },
    },
    workflow_mode: 'attachment_standard', variation_types: [], variation_plan_count: 0, source_task_group_id: null,
    group_number: number, group_name: `group ${number}`, status: 'succeeded', selected_image_types: ['gift_scene'], input_assets: [], tasks,
    statistics: { total: tasks.length, queued: 0, running: 0, succeeded: tasks.length, failed: 0, cancelled: 0 }, progress: 100,
    created_by: 'user', created_at: `2026-08-${10 + number}T00:00:00Z`, updated_at: `2026-08-${10 + number}T00:00:00Z`,
  }
}

describe('deriveAttachmentResultData', () => {
  it('keeps an older final beside the latest batch and keeps replaced outputs in history', () => {
    const older = group('old', 1, [task('old-1', 1, output('old-final'))])
    const latest = group('new', 2, [task('new-1', 1, output('new-slot'))])
    const result = deriveAttachmentResultData('gift_scene', [older, latest], {
      module_key: 'gift_scene', current_final_output_id: 'old-final', results_cleared_at: null, state_version: 2,
      visible_output_count: 2, history_output_count: 0, pending_review_count: 0, approved_count: 2, rejected_count: 0,
    })
    expect(result.current.map((item) => item.output.id)).toEqual(['old-final', 'new-slot'])
    expect(result.final?.output.id).toBe('old-final')
  })

  it('hides discarded outputs from current slots without deleting history', () => {
    const result = deriveAttachmentResultData('gift_scene', [group('old', 1, [task('old-1', 1, output('discarded', true))])], {
      module_key: 'gift_scene', current_final_output_id: null, results_cleared_at: '2026-08-19T10:00:00Z', state_version: 3,
      visible_output_count: 0, history_output_count: 1, pending_review_count: 0, approved_count: 0, rejected_count: 0,
    })
    expect(result.current).toHaveLength(0)
    expect(result.history.map((item) => item.output.id)).toEqual(['discarded'])
  })
})
