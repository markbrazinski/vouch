import { useCallback, useMemo, useReducer } from 'react';
import type { Command, VouchViewModel } from '../view-models/types';
import { INITIAL_STATE, reduce, selectView, type VouchState } from '../view-models/fixture-adapter';
import { AppShell } from './AppShell';
import { IncomingPage } from '../features/incoming/IncomingPage';
import { QualityDecisionDrawer } from '../features/incoming/QualityDecisionDrawer';
import { TodayPage } from '../features/today/TodayPage';
import { DecisionRecordPage } from '../features/records/DecisionRecordPage';
import { RecordsPage } from '../features/records/RecordsPage';
import { SuppliersPage } from '../features/suppliers/SuppliersPage';

export function VouchScreens({
  vm,
  dispatch,
}: {
  vm: VouchViewModel;
  dispatch: (cmd: Command) => void;
}) {
  return (
    <AppShell
      screen={vm.screen}
      incomingBadge={vm.navBadge}
      onNavigate={(screen) => dispatch({ type: 'NAVIGATE', screen })}
      overlay={
        vm.drawer ? (
          <QualityDecisionDrawer
            row={vm.drawer.row}
            resolved={vm.drawer.resolved}
            resumeSteps={vm.drawer.resumeSteps}
            dispatch={dispatch}
          />
        ) : null
      }
    >
      {vm.screen === 'incoming' && vm.incoming && (
        <IncomingPage vm={vm.incoming} dispatch={dispatch} />
      )}
      {vm.screen === 'today' && vm.today && <TodayPage vm={vm.today} dispatch={dispatch} />}
      {vm.screen === 'record' && vm.record && (
        <DecisionRecordPage vm={vm.record} dispatch={dispatch} />
      )}
      {vm.screen === 'suppliers' && vm.suppliers && <SuppliersPage vm={vm.suppliers} />}
      {vm.screen === 'records' && vm.records && <RecordsPage vm={vm.records} dispatch={dispatch} />}
    </AppShell>
  );
}

export function VouchApp({ initialState = INITIAL_STATE }: { initialState?: VouchState }) {
  const [state, raw] = useReducer(reduce, initialState);
  const dispatch = useCallback((cmd: Command) => raw(cmd), []);
  const vm = useMemo(() => selectView(state), [state]);
  return <VouchScreens vm={vm} dispatch={dispatch} />;
}
