/**
 * US geographic map (react-simple-maps + bundled us-atlas topojson) with two
 * views:
 *
 *  - "Clusters": feedback `map_points` merged by city (or a coarse lat/lng
 *    bucket) into bubbles sized by count and colored by average severity.
 *    Clicking a bubble reveals that cluster's individual feedback items below
 *    the map, each linking to its admin detail page.
 *  - "By state": a choropleth shading each state by feedback volume, driven by
 *    the analytics `by_state` aggregate.
 *
 * The topojson is imported locally so the map works fully offline (no tile
 * server or API key required).
 */
import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import {
  ComposableMap,
  Geographies,
  Geography,
  Marker,
} from 'react-simple-maps'
import type { MapPoint, StateAgg } from '../../api/client'
import usStates from '../../assets/us-states-10m.json'
import { STATE_NAME_TO_CODE, STATE_CODE_TO_NAME } from '../../utils/stateNames'
import { severityColor } from './chartTheme'
import { useSort, type SortGetter } from '../../hooks/useSort'
import styles from './FeedbackMap.module.css'

// Sort getters for the clicked-cluster feedback list.
const CLUSTER_SORT: Record<string, SortGetter<MapPoint>> = {
  severity: (m) => m.severity,
  sentiment: (m) => m.sentiment,
  department: (m) => m.department,
}

// us-atlas topology; react-simple-maps consumes the raw topojson object.
const GEO = usStates as unknown as Record<string, unknown>

type View = 'clusters' | 'states'

interface Cluster {
  key: string
  label: string
  longitude: number
  latitude: number
  count: number
  avgSeverity: number | null
  sentiments: Record<string, number>
  departments: Record<string, number>
  members: MapPoint[]
}

/** Bubble radius from cluster size: grows sublinearly, clamped for sanity. */
function radiusFor(count: number): number {
  return Math.min(6 + count * 2.4, 30)
}

/** Highest-frequency key in a count map, or "—" when empty. */
function topKey(counts: Record<string, number>): string {
  let best = '—'
  let bestN = -1
  for (const [k, n] of Object.entries(counts)) {
    if (n > bestN) {
      best = k
      bestN = n
    }
  }
  return best
}

/** Base state fill (unlit land) on the light map. */
const STATE_BASE = '#EAF2FB'
const STATE_STROKE = '#C7DBF0'

/** Blue choropleth fill scaled by a state's share of the max count. */
function choroplethColor(count: number, max: number): string {
  if (count <= 0 || max <= 0) return STATE_BASE
  const t = count / max
  if (t > 0.8) return '#0B3B77'
  if (t > 0.6) return '#0059B8'
  if (t > 0.4) return '#3A82CC'
  if (t > 0.2) return '#7FB0E0'
  return '#B7D3EF'
}

interface Props {
  points: MapPoint[]
  byState: StateAgg[]
}

export default function FeedbackMap({ points, byState }: Props) {
  const [view, setView] = useState<View>('clusters')

  const clusters = useMemo<Cluster[]>(() => {
    const groups = new Map<string, MapPoint[]>()
    for (const p of points) {
      if (p.latitude == null || p.longitude == null) continue
      const key =
        p.city && p.state
          ? `${p.city}, ${p.state}`
          : `${p.latitude.toFixed(1)},${p.longitude.toFixed(1)}`
      const bucket = groups.get(key)
      if (bucket) bucket.push(p)
      else groups.set(key, [p])
    }

    const result: Cluster[] = []
    for (const [key, members] of groups) {
      let latSum = 0
      let lngSum = 0
      let sevSum = 0
      let sevN = 0
      const sentiments: Record<string, number> = {}
      const departments: Record<string, number> = {}
      for (const m of members) {
        latSum += m.latitude
        lngSum += m.longitude
        if (typeof m.severity === 'number') {
          sevSum += m.severity
          sevN += 1
        }
        const s = m.sentiment ?? 'unknown'
        sentiments[s] = (sentiments[s] ?? 0) + 1
        if (m.department) departments[m.department] = (departments[m.department] ?? 0) + 1
      }
      const first = members[0]
      const label = first.city && first.state ? `${first.city}, ${first.state}` : key
      result.push({
        key,
        label,
        latitude: latSum / members.length,
        longitude: lngSum / members.length,
        count: members.length,
        avgSeverity: sevN ? Math.round((sevSum / sevN) * 10) / 10 : null,
        sentiments,
        departments,
        members,
      })
    }
    return result.sort((a, b) => a.count - b.count)
  }, [points])

  const [hovered, setHovered] = useState<Cluster | null>(null)
  const [selected, setSelected] = useState<Cluster | null>(null)
  const [hoveredState, setHoveredState] = useState<string | null>(null)

  // Sortable list of the selected cluster's feedback items.
  const clusterSort = useSort(selected?.members ?? [], CLUSTER_SORT, 'severity', 'desc')

  // Fast lookups for the choropleth: full state name → aggregate.
  const stateByName = useMemo(() => {
    const m = new Map<string, StateAgg>()
    for (const s of byState) {
      const name = STATE_CODE_TO_NAME[s.state]
      if (name) m.set(name, s)
    }
    return m
  }, [byState])

  const maxStateCount = useMemo(
    () => byState.reduce((max, s) => Math.max(max, s.count), 0),
    [byState]
  )

  const totalPlotted = clusters.reduce((sum, c) => sum + c.count, 0)
  const hoveredAgg = hoveredState ? stateByName.get(hoveredState) : undefined

  return (
    <div className={styles.mapCard}>
      <div className={styles.mapHeader}>
        <div>
          <h3 className={styles.mapTitle}>Geographic clustering</h3>
          <span className={styles.mapSubtitle}>
            {view === 'clusters'
              ? `${totalPlotted} located feedback · ${clusters.length} clusters`
              : `${byState.length} states with feedback`}
          </span>
        </div>

        <div className={styles.headerRight}>
          <div className={styles.toggle} role="tablist" aria-label="Map view">
            <button
              type="button"
              role="tab"
              aria-selected={view === 'clusters'}
              className={`${styles.toggleBtn} ${view === 'clusters' ? styles.toggleActive : ''}`}
              onClick={() => setView('clusters')}
            >
              Clusters
            </button>
            <button
              type="button"
              role="tab"
              aria-selected={view === 'states'}
              className={`${styles.toggleBtn} ${view === 'states' ? styles.toggleActive : ''}`}
              onClick={() => setView('states')}
            >
              By state
            </button>
          </div>

          <div className={styles.hoverInfo} aria-live="polite">
            {view === 'clusters' && hovered ? (
              <>
                <strong>{hovered.label}</strong>
                <span>
                  {hovered.count} feedback · avg severity{' '}
                  {hovered.avgSeverity != null ? `${hovered.avgSeverity}/10` : '—'}
                </span>
                <span>
                  {topKey(hovered.sentiments)} · {topKey(hovered.departments)}
                </span>
              </>
            ) : view === 'states' && hoveredState ? (
              <>
                <strong>{hoveredState}</strong>
                <span>
                  {hoveredAgg ? `${hoveredAgg.count} feedback` : 'No feedback'}
                  {hoveredAgg?.avg_severity != null
                    ? ` · avg severity ${hoveredAgg.avg_severity}/10`
                    : ''}
                </span>
              </>
            ) : (
              <span className={styles.hoverHint}>
                {view === 'clusters'
                  ? 'Hover a cluster; click to list its feedback'
                  : 'Hover a state for its totals'}
              </span>
            )}
          </div>
        </div>
      </div>

      {view === 'clusters' && clusters.length === 0 ? (
        <p className={styles.empty}>No geo-located feedback yet.</p>
      ) : (
        <div className={styles.mapWrapper}>
          <ComposableMap
            projection="geoAlbersUsa"
            projectionConfig={{ scale: 1000 }}
            width={880}
            height={500}
            style={{ width: '100%', height: 'auto' }}
          >
            <Geographies geography={GEO}>
              {({ geographies }) =>
                geographies.map((geo) => {
                  const name = geo.properties?.name as string | undefined
                  const agg = name ? stateByName.get(name) : undefined
                  const fill =
                    view === 'states'
                      ? choroplethColor(agg?.count ?? 0, maxStateCount)
                      : STATE_BASE
                  return (
                    <Geography
                      key={geo.rsmKey}
                      geography={geo}
                      fill={fill}
                      stroke={STATE_STROKE}
                      strokeWidth={0.6}
                      onMouseEnter={() =>
                        view === 'states' && name
                          ? setHoveredState(STATE_NAME_TO_CODE[name] ?? name)
                          : undefined
                      }
                      onMouseLeave={() =>
                        view === 'states' ? setHoveredState(null) : undefined
                      }
                      style={{
                        default: { outline: 'none' },
                        hover: {
                          fill: view === 'states' ? '#04407F' : '#DCEAF9',
                          outline: 'none',
                          cursor: view === 'states' ? 'pointer' : 'default',
                        },
                        pressed: { outline: 'none' },
                      }}
                    />
                  )
                })
              }
            </Geographies>

            {view === 'clusters' &&
              clusters.map((c) => {
                const r = radiusFor(c.count)
                const color = severityColor(c.avgSeverity)
                const active = hovered?.key === c.key || selected?.key === c.key
                return (
                  <Marker
                    key={c.key}
                    coordinates={[c.longitude, c.latitude]}
                    onMouseEnter={() => setHovered(c)}
                    onMouseLeave={() => setHovered(null)}
                    onClick={() => setSelected((prev) => (prev?.key === c.key ? null : c))}
                  >
                    <circle
                      r={r}
                      fill={color}
                      fillOpacity={active ? 0.9 : 0.55}
                      stroke={active ? '#0B1E33' : color}
                      strokeWidth={active ? 2 : 1}
                      style={{ cursor: 'pointer', transition: 'fill-opacity 0.15s ease' }}
                    />
                    {c.count > 1 && (
                      <text
                        textAnchor="middle"
                        dy={4}
                        fontSize={Math.min(12, r)}
                        fontWeight={700}
                        fill="#fff"
                        style={{ pointerEvents: 'none' }}
                      >
                        {c.count}
                      </text>
                    )}
                    <title>{`${c.label}: ${c.count} feedback`}</title>
                  </Marker>
                )
              })}
          </ComposableMap>

          {view === 'clusters' ? (
            <div className={styles.legend}>
              <span className={styles.legendTitle}>Avg severity</span>
              <span className={styles.legendItem}>
                <i style={{ background: '#2E7D32' }} /> 1-3
              </span>
              <span className={styles.legendItem}>
                <i style={{ background: '#F57C00' }} /> 4-6
              </span>
              <span className={styles.legendItem}>
                <i style={{ background: '#EF6C00' }} /> 7-8
              </span>
              <span className={styles.legendItem}>
                <i style={{ background: '#D32F2F' }} /> 9-10
              </span>
              <span className={styles.legendNote}>Bubble size = feedback count</span>
            </div>
          ) : (
            <div className={styles.legend}>
              <span className={styles.legendTitle}>Feedback volume</span>
              <span className={styles.legendItem}>
                <i style={{ background: '#B7D3EF' }} /> Low
              </span>
              <span className={styles.legendItem}>
                <i style={{ background: '#3A82CC' }} /> Med
              </span>
              <span className={styles.legendItem}>
                <i style={{ background: '#0B3B77' }} /> High
              </span>
              <span className={styles.legendNote}>Darker = more feedback</span>
            </div>
          )}
        </div>
      )}

      {/* Clicked-cluster feedback list (clusters view only). */}
      {view === 'clusters' && selected && (
        <div className={styles.detailPanel}>
          <div className={styles.detailPanelHead}>
            <h4 className={styles.detailPanelTitle}>
              {selected.label} — {selected.count} feedback
            </h4>
            <button
              type="button"
              className={styles.detailClose}
              onClick={() => setSelected(null)}
              aria-label="Close cluster details"
            >
              ✕
            </button>
          </div>
          <div className={styles.detailSortBar}>
            <span className={styles.detailSortLabel}>Sort:</span>
            {(['severity', 'sentiment', 'department'] as const).map((key) => {
              const active = clusterSort.sortKey === key
              return (
                <button
                  key={key}
                  type="button"
                  className={`${styles.detailSortBtn} ${active ? styles.detailSortActive : ''}`}
                  onClick={() => clusterSort.toggleSort(key)}
                >
                  {key.charAt(0).toUpperCase() + key.slice(1)}
                  <span className={styles.detailSortArrow} aria-hidden="true">
                    {active ? (clusterSort.sortDir === 'asc' ? '▲' : '▼') : '⇅'}
                  </span>
                </button>
              )
            })}
          </div>

          <ul className={styles.detailList}>
            {clusterSort.sorted.map((m) => (
              <li key={m.feedback_id} className={styles.detailItem}>
                <span
                  className={styles.sevDot}
                  style={{ background: severityColor(m.severity) }}
                  aria-hidden="true"
                />
                <span className={styles.sevValue}>
                  {m.severity != null ? `${m.severity}/10` : '—'}
                </span>
                <span className={styles.detailMeta}>
                  {m.sentiment ?? 'unknown'} · {m.department ?? 'Unassigned'}
                </span>
                <Link className={styles.detailLink} to={`/admin/feedback/${m.feedback_id}`}>
                  View feedback →
                </Link>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  )
}
