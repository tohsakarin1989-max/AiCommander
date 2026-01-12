import React, { useState } from 'react'
import { Table, Card, Tag, Descriptions, Empty, Alert, Button, Space, message } from 'antd'
import { useQuery } from '@tanstack/react-query'
import { caseApi, Case } from '../../services/cases'

const CaseFeatures: React.FC = () => {
  const { data: cases, isLoading } = useQuery({
    queryKey: ['cases'],
    queryFn: () => caseApi.getCases(),
  })

  const { data: preprocessStatus } = useQuery({
    queryKey: ['preprocess-status'],
    queryFn: () => caseApi.getPreprocessStatus(),
    refetchInterval: 5000,
  })

  const [selected, setSelected] = useState<Case | null>(null)
  const [selectedRowKeys, setSelectedRowKeys] = useState<React.Key[]>([])

  const columns = [
    {
      title: '案件编号',
      dataIndex: 'case_number',
      key: 'case_number',
    },
    {
      title: '发生时间',
      dataIndex: 'occurred_time',
      key: 'occurred_time',
    },
    {
      title: '地点',
      dataIndex: 'location',
      key: 'location',
    },
    {
      title: '预处理状态',
      dataIndex: 'features',
      key: 'features',
      render: (features: any) =>
        features && Object.keys(features).length > 0 ? (
          <Tag color="green">已预处理</Tag>
        ) : (
          <Tag>未预处理</Tag>
        ),
    },
  ]

  const rowSelection = {
    selectedRowKeys,
    onChange: (keys: React.Key[]) => setSelectedRowKeys(keys),
    onSelect: (record: Case) => setSelected(record),
  }

  const handleBatchPreprocess = async () => {
    if (!selectedRowKeys.length) {
      message.warning('请先选择需要预处理的案件')
      return
    }
    try {
      await Promise.all(
        selectedRowKeys.map((id) => caseApi.preprocessCase(id as number)),
      )
      message.success(`已提交 ${selectedRowKeys.length} 条预处理任务`)
      setSelectedRowKeys([])
    } catch (e: any) {
      message.error(`批量预处理失败：${e.message || e}`)
    }
  }

  const renderDetail = () => {
    if (!selected) {
      return <Empty description="请选择左侧案件以查看结构化结果" />
    }
    const features = selected.features || {}
    const basic = features.basic || {}
    const geo = features.geo || {}
    const modus = features.modus || {}
    const actors = features.actors || {}
    const oil = features.oil || {}
    const flow = features.flow || {}
    const risk = features.risk || {}
    const confidence = typeof features.confidence === 'number' ? features.confidence : null

    const lowConfidence = confidence !== null && confidence < 0.7

    const actorFacts = actors.facts || {}
    const actorClues = actors.clues || {}
    const actorHypotheses = actors.hypotheses || {}

    const oilFacts = oil.facts || {}
    const oilClues = oil.clues || {}
    const oilHypotheses = oil.hypotheses || {}

    return (
      <>
        <Card title="标准化摘要" style={{ marginBottom: 16 }}>
          {lowConfidence && (
            <p style={{ color: '#d4380d', marginBottom: 8 }}>
              本次预处理整体置信度较低（{(confidence! * 100).toFixed(0)}%），建议人工仔细复核以下内容。
            </p>
          )}
          <p>
            <strong>案名：</strong>
            {basic.title || '（未生成）'}
          </p>
          <p>{basic.summary || '暂无摘要，请确认预处理任务是否完成。'}</p>
        </Card>

        <Card title="结构化特征">
          <Descriptions column={1} size="small" bordered>
            <Descriptions.Item label="案件类型">
              {basic.case_type || selected.case_type || '未知'}
            </Descriptions.Item>
            <Descriptions.Item label="时间（标准化）">
              {basic.time || selected.occurred_time}
            </Descriptions.Item>
            <Descriptions.Item label="地点（标准化）">
              {basic.location || selected.location}
            </Descriptions.Item>
            <Descriptions.Item label="地理信息">
              纬度：{geo.latitude ?? selected.latitude ?? '未知'} ，经度：
              {geo.longitude ?? selected.longitude ?? '未知'} ，区域：
              {geo.region || '未知'} ，地点类型：
              {geo.place_type || '未知'}
            </Descriptions.Item>

            <Descriptions.Item label="涉案人员/车辆（事实）">
              角色：{(actorFacts.known_roles || []).join('，') || '未知'}
              <br />
              车辆：
              {(actorFacts.known_vehicles || [])
                .map((v: any) => `${v.plate || '未知车牌'}（${v.type || '类型未知'}）`)
                .join('，') || '未知'}
            </Descriptions.Item>
            <Descriptions.Item label="涉案人员/车辆（线索）">
              可能角色：{(actorClues.possible_roles || []).join('，') || '暂无明显线索'}
              <br />
              备注：{actorClues.notes || '—'}
            </Descriptions.Item>
            <Descriptions.Item label="涉案人员/车辆（推测，需核实）">
              团伙结构推测：{actorHypotheses.suspected_structure || '暂无可靠推测'}
            </Descriptions.Item>

            <Descriptions.Item label="涉油特征（事实）">
              油品类型：{oilFacts.oil_type || selected.oil_type || '未知'}
              <br />
              数量：{oilFacts.volume ?? selected.oil_volume ?? '未知'}
              <br />
              价值（元）：{oilFacts.value ?? selected.oil_value ?? '未知'}
              <br />
              目标设施：{oilFacts.facility_type || selected.facility_type || '未知'}
            </Descriptions.Item>
            <Descriptions.Item label="涉油特征（线索）">
              现场线索：
              {(oilClues.scene_observations || []).join('，') || '暂无明显线索'}
            </Descriptions.Item>
            <Descriptions.Item label="涉油特征（推测，需核实）">
              可能风险：{oilHypotheses.possible_risk || '暂无可靠推测'}
            </Descriptions.Item>

            <Descriptions.Item label="油品流向">
              上游来源：{flow.upstream_source || selected.upstream_source || '未知'}
              <br />
              下游去向：
              {(flow.downstream_destination || []).join('，') ||
                selected.downstream_destination ||
                '未知'}
            </Descriptions.Item>
            <Descriptions.Item label="风险评估">
              等级：{risk.level || '未知'}
              <br />
              因素：{(risk.factors || []).join('，') || '未知'}
            </Descriptions.Item>
            <Descriptions.Item label="标签">
              {(features.tags || []).length
                ? (features.tags || []).join('，')
                : '暂无标签'}
            </Descriptions.Item>
          </Descriptions>
        </Card>
      </>
    )
  }

  return (
    <div>
      {preprocessStatus && (
        <Alert
          type="info"
          showIcon
          style={{ marginBottom: 16 }}
          message={`预处理队列：排队 ${preprocessStatus.pending}，处理中 ${
            preprocessStatus.processing
          }，平均耗时 ${
            preprocessStatus.avg_duration_seconds != null
              ? `${Math.round(preprocessStatus.avg_duration_seconds)} 秒`
              : '暂无数据'
          }`}
        />
      )}

      <h2>案件预处理与结构化结果</h2>
      <p style={{ marginBottom: 16 }}>
        说明：左侧显示案件列表及预处理状态，右侧展示选中案件的摘要与结构化特征，方便人工核查大模型预处理效果。
      </p>
      <div style={{ display: 'flex', gap: 16 }}>
        <div style={{ flex: 1 }}>
          <Card
            title={
              <Space>
                <span>案件列表</span>
                <Button
                  size="small"
                  onClick={handleBatchPreprocess}
                  disabled={!selectedRowKeys.length}
                >
                  批量预处理
                </Button>
              </Space>
            }
          >
            <Table
              rowSelection={rowSelection}
              columns={columns}
              dataSource={cases}
              loading={isLoading}
              rowKey="id"
              size="small"
              pagination={{ pageSize: 10 }}
              onRow={(record) => ({
                onClick: () => setSelected(record),
              })}
            />
          </Card>
        </div>
        <div style={{ flex: 1 }}>{renderDetail()}</div>
      </div>
    </div>
  )
}

export default CaseFeatures


