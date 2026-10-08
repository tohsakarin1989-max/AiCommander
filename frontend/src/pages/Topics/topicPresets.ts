import type { TopicDefinition, TopicSourceContext, TopicWindow } from '../../services/analysisTopics'

// Static entry points for existing services, not natural-language generated plans.
export const topicPresets: Array<{ kind: NonNullable<TopicDefinition['question_kind']>; title: string; description: string; entry: string; window: TopicWindow }> = [
  { kind: 'condition_changes', title: '近期案件条件变化', description: '比较授权案件的手法、油品、地点条件及资料缺口；可继续收窄条件。', entry: '/topics', window: { mode: 'rolling', days: 30, anchor_hour: 0 } },
  { kind: 'case_gaps', title: '本案资料与成果变化', description: '带入一个案件，关注缺项、已有过程与成果，不扩成全库案件。', entry: '/cases', window: { mode: 'fixed' } },
  { kind: 'facility_context', title: '本设施资料与关联变化', description: '带入一个设施，关注已有资料与明确关联，不把邻近当涉案。', entry: '/jurisdiction#facility-lookup', window: { mode: 'fixed' } },
]

export function contextQuestionKind(source?: TopicSourceContext): NonNullable<TopicDefinition['question_kind']> {
  return source?.kind === 'case' ? 'case_gaps' : source?.kind === 'facility' ? 'facility_context' : 'condition_changes'
}
