import wx
import serial
import threading
import time
import json
import csv
import numpy as np
from lib.floatcontrol import FloatCtrl
from wxmplot import PlotPanel

# constants (update these with real values, code adjusts automatically)
MAX_VOLTAGE = 40.5
MIN_VOLTAGE = 0
MAX_AMPERAGE = 40
MIN_AMPERAGE = 0
MAX_RPM = 3420
MIN_RPM = 0
MAX_CONTROLLER_TEMP = 200
MIN_CONTROLLER_TEMP = 50

class LogPane(wx.TextCtrl):
    def __init__(self, parent):
        super(LogPane, self).__init__(parent, wx.NewId(), style=wx.TE_MULTILINE | wx.TE_READONLY)
        monospaceFont = wx.Font(14, wx.FONTFAMILY_TELETYPE, wx.NORMAL, wx.NORMAL)
        self.SetFont(monospaceFont)
        self.paused = False

    def AddLine(self, message):
        if self.paused == False:
            if self.GetNumberOfLines() > 100:
                self.Remove(0, self.GetLineLength(0) + 1)
            self.write(message)


class TelemetrySoftware(wx.Frame):
    def __init__(self):
        super(TelemetrySoftware, self).__init__(None, title="URSS Telemetry")

        # initial data values
        self.voltage = MAX_VOLTAGE
        self.amperage = MIN_AMPERAGE
        self.rpm = MIN_RPM
        self.controllerTemp = MIN_CONTROLLER_TEMP

        # plot data
        self.voltage_values = []
        self.amperage_values = []
        self.timestamps = []
        self.goalVoltageLineDisplayed = False

        # fake telemetry flag
        self.fake_telemetry = True
        self.fake_telemetry_counter = 0

        self.Maximize(True)
        self.InitUI()
        self.InitTelemetryThread()
        self.Centre()
        self.Show()

    def InitUI(self):
        panelRoot = wx.Panel(self)
        panelRootSizer = wx.BoxSizer(wx.VERTICAL)

        topSplitter = wx.SplitterWindow(panelRoot, style=wx.SP_LIVE_UPDATE | wx.SP_3DSASH)
        topVerticalSplitter = wx.SplitterWindow(topSplitter, style=wx.SP_LIVE_UPDATE | wx.SP_3DSASH)

        #############################################
        #   TOP-LEFT PANEL (STATUS AND CONTROLS)    #
        #############################################

        panelTopLeft = wx.Panel(topVerticalSplitter)
        panelTopLeftSizer = wx.BoxSizer(wx.VERTICAL)

        # create gauges and set initial values
        self.voltageGauge = wx.Gauge(panelTopLeft, -1, MAX_VOLTAGE - MIN_VOLTAGE, (0, 0), (250, 25))
        self.voltageGauge.SetValue(self.voltage - MIN_VOLTAGE)

        self.amperageGauge = wx.Gauge(panelTopLeft, -1, MAX_AMPERAGE - MIN_AMPERAGE, (0, 0), (250, 25))
        self.amperageGauge.SetValue(self.amperage - MIN_AMPERAGE)

        self.rpmGauge = wx.Gauge(panelTopLeft, -1, MAX_RPM - MIN_RPM, (0, 0), (250, 25))
        self.rpmGauge.SetValue(self.rpm - MIN_RPM)

        self.controllerTempGauge = wx.Gauge(panelTopLeft, -1, MAX_CONTROLLER_TEMP - MIN_CONTROLLER_TEMP, (0, 0), (250, 25))
        self.controllerTempGauge.SetValue(self.controllerTemp - MIN_CONTROLLER_TEMP)

        # create labels
        self.voltageLabel = wx.StaticText(panelTopLeft, -1, "Voltage (" + str(self.voltage) + ")")
        self.amperagLabel = wx.StaticText(panelTopLeft, -1, "Amperage (" + str(self.amperage) + ")")
        self.rpmLabel = wx.StaticText(panelTopLeft, -1, "RPM (" + str(self.rpm) + ")")
        self.controllerTempLabel = wx.StaticText(panelTopLeft, -1, "Controller Temperature (" + str(self.controllerTemp) + ")")

        # Add voltage Gauge and label to BoxSizer
        panelTopLeftSizer.Add(self.voltageLabel, 0, wx.ALIGN_CENTRE_HORIZONTAL)
        panelTopLeftSizer.Add(self.voltageGauge, 1, wx.ALIGN_CENTRE_HORIZONTAL)
        # Add amperage Gauge and label to BoxSizer
        panelTopLeftSizer.Add(self.amperagLabel, 0, wx.ALIGN_CENTRE_HORIZONTAL)
        panelTopLeftSizer.Add(self.amperageGauge, 1, wx.ALIGN_CENTRE_HORIZONTAL)
        # Add RPM Gauge and label to BoxSizer
        panelTopLeftSizer.Add(self.rpmLabel, 0, wx.ALIGN_CENTRE_HORIZONTAL)
        panelTopLeftSizer.Add(self.rpmGauge, 1, wx.ALIGN_CENTRE_HORIZONTAL)
        # Add controller temp Gauge and label to BoxSizer
        panelTopLeftSizer.Add(self.controllerTempLabel, 0, wx.ALIGN_CENTRE_HORIZONTAL)
        panelTopLeftSizer.Add(self.controllerTempGauge, 1, wx.ALIGN_CENTRE_HORIZONTAL)

        # Add BoxSizer to panel
        panelTopLeft.SetSizer(panelTopLeftSizer)

        ################################
        #   TOP-RIGHT PANEL (GRAPH)    #
        ################################

        panelTopRight = wx.Panel(topVerticalSplitter)
        panelTopRightSizer = wx.BoxSizer(wx.VERTICAL)

        # create top button bar
        topButtonPanel = wx.Panel(panelTopRight, -1)
        topButtonSizer = wx.BoxSizer(wx.HORIZONTAL)

        goalVoltageLabel = wx.StaticText(topButtonPanel, -1, '    End Goal Voltage Value (V):    ')
        self.goalEndVoltage = FloatCtrl(topButtonPanel, size=(100, -1), value=34.5, precision=1)
        endTimeLabel = wx.StaticText(topButtonPanel, -1, '    End Time (min):    ')
        self.endTime = FloatCtrl(topButtonPanel, size=(100, -1), value=120, precision=0)
        plotGoalVoltageButton = wx.Button(topButtonPanel, -1, 'Plot Goal Voltage', size=(250, -1))
        plotGoalVoltageButton.Bind(wx.EVT_BUTTON, self.OnPlotGoalVoltage)

        topButtonSizer.Add(goalVoltageLabel)
        topButtonSizer.Add(self.goalEndVoltage)
        topButtonSizer.Add(endTimeLabel)
        topButtonSizer.Add(self.endTime)
        topButtonSizer.Add(plotGoalVoltageButton)

        topButtonPanel.SetSizer(topButtonSizer)
        topButtonSizer.Fit(topButtonPanel)

        # create plot panel

        self.plotPanel = PlotPanel(panelTopRight)

        # create bottom button bar

        bottomButtonPanel = wx.Panel(panelTopRight, -1)
        bottomButtonSizer = wx.BoxSizer(wx.HORIZONTAL)

        exportButton = wx.Button(bottomButtonPanel, -1, 'Export Plot to CSV', size=(250, -1))
        exportButton.Bind(wx.EVT_BUTTON, self.ExportPlotDataToCSV)
        resetButton = wx.Button(bottomButtonPanel, -1, 'Reset Graph', size=(250, -1))
        resetButton.Bind(wx.EVT_BUTTON, self.ResetGraph)

        bottomButtonSizer.Add(exportButton, 1)
        bottomButtonSizer.Add(resetButton, 1)

        bottomButtonPanel.SetSizer(bottomButtonSizer)
        bottomButtonSizer.Fit(bottomButtonPanel)

        # Add panels to top right sizer
        panelTopRightSizer.Add(topButtonPanel, 0, wx.EXPAND | wx.ALL)
        panelTopRightSizer.Add(self.plotPanel, 1, wx.EXPAND | wx.ALL)
        panelTopRightSizer.Add(bottomButtonPanel, 0)

        # Add BoxSizer to panel
        panelTopRight.SetSizer(panelTopRightSizer)

        # add top panels to vertical splitter
        topVerticalSplitter.SplitVertically(panelTopLeft, panelTopRight)
        topVerticalSplitter.SetSashGravity(0.25)

        #############################################
        #   BOTTOM PANEL (LOG & TELEMETRY INPUT)    #
        #############################################

        panelBottom = wx.Panel(topSplitter)
        panelBottomSizer = wx.BoxSizer(wx.VERTICAL)

        self.logPane = LogPane(panelBottom)

        logPaneLabel = wx.StaticText(panelBottom, label="Telemetry Message Log (Last 100 messages shown):")
        logPaneLabel.SetFont(wx.Font(14, wx.FONTFAMILY_TELETYPE, wx.NORMAL, wx.BOLD))
        panelBottomSizer.Add(logPaneLabel, 0, wx.ALIGN_TOP)
        panelBottomSizer.Add(self.logPane, 1, wx.EXPAND | wx.ALL)

        panelBottom.SetSizer(panelBottomSizer)

        topSplitter.SplitHorizontally(topVerticalSplitter, panelBottom)
        topSplitter.SetSashGravity(0.75)

        panelRootSizer.Add(topSplitter, 1, wx.EXPAND | wx.ALL)
        panelRoot.SetSizer(panelRootSizer)

    def InitTelemetryThread(self):
        print("Initializing telemetry thread...")

        if not self.fake_telemetry:
            success = False
            try:
                self.serial = serial.Serial("/dev/cu.usbserial-DN01236H", 57600)
                success = True
                if not self.serial.is_open:
                    success = False
            except Exception:
                print("Could not open serial radio!")

            if not success:
                # If we fail to connect to serial, display error and then quitself.
                dial = wx.MessageDialog(None,
                                        'Could not connect to serial radio. Please plug in the serial radio adapter and restart your computer!',
                                        'Error',
                                        wx.OK | wx.ICON_ERROR)
                dial.ShowModal()
                exit(0)

        thread = threading.Thread(target=self.TelemetryThread)
        thread.start()

        print("Done.")

    def TelemetryCallback(self, message):
        timestamp = int(round(time.time()))
        if len(self.timestamps) == 0:
            self.t0 = timestamp

        self.logPane.AddLine(message)

        if not self.fake_telemetry:
            # parse JSON message
            m = json.loads(message)
            split_message = m['message'].split(',')
            if split_message[0] == 'BATTERY':
                self.voltage = float(split_message[2][2:]) / 1000
                self.amperage = float(split_message[4][2:]) / 1000 * -1

        # add values to lists
        self.voltage_values.append(self.voltage)
        self.amperage_values.append(self.amperage)
        self.timestamps.append(timestamp - self.t0)

        # update gauges and plot
        self.UpdateGauges()
        self.UpdatePlot()

    def UpdateGauges(self):
        self.voltageGauge.SetValue(self.voltage - MIN_VOLTAGE)
        self.voltageLabel.SetLabel("Voltage (" + str(self.voltage) + "/" + str(MAX_VOLTAGE) + ")")
        self.amperageGauge.SetValue(self.amperage - MIN_AMPERAGE)
        self.amperagLabel.SetLabel("Amperage (" + str(self.amperage) + "/" + str(MAX_AMPERAGE) + ")")
        self.rpmGauge.SetValue(self.rpm - MIN_RPM)
        self.rpmLabel.SetLabelText("RPM (" + str(self.rpm) + "/" + str(MAX_RPM) + ")")
        self.controllerTempGauge.SetValue(self.controllerTemp - MIN_CONTROLLER_TEMP)
        self.controllerTempLabel.SetLabelText("Controller Temperature (" + str(self.controllerTemp) + ")")

    def UpdatePlot(self):
        v_n = len(self.voltage_values)
        tdat = np.array(self.timestamps)
        vdat = np.array(self.voltage_values)
        adat = np.array(self.amperage_values)
        if v_n <= 2:
            self.plotPanel.plot(tdat, vdat,
                                xlabel='Time (s from start)',
                                ylabel='Voltage (V)',
                                label='Voltage',
                                style='solid')
            self.plotPanel.oplot(tdat, adat,
                                 y2label='Amperage (A)',
                                 side='right',
                                 label='Amperage',
                                 style='long dashed',
                                 show_legend=True)
        else:
            self.plotPanel.update_line(0, tdat, vdat, draw=True)
            self.plotPanel.update_line(1, tdat, adat, draw=True)

    def OnPlotGoalVoltage(self, event=None):
        v = float(self.goalEndVoltage.GetValue())
        t = int(self.endTime.GetValue()) * 60
        if len(self.voltage_values) > 2 and v <= self.voltage and t >= 0:
            tdat = np.linspace(0, t, t)
            vdat = np.linspace(self.voltage_values[0], v, t)
            if not self.goalVoltageLineDisplayed:
                self.goalVoltageLineDisplayed = True
                self.plotPanel.oplot(tdat, vdat, label='Goal Voltage', style='short dashed')
            else:
                self.plotPanel.update_line(2, tdat, vdat, draw=True)

    def ResetGraph(self, event=None):
        del self.timestamps[:]
        del self.voltage_values[:]
        del self.amperage_values[:]
        self.goalVoltageLineDisplayed = False

    def ExportPlotDataToCSV(self, event=None):
        filename = 'exported_data_' + str(int(round(time.time()*1000))) + '.csv'
        with open(filename, 'wb') as datafile:
            w = csv.writer(datafile)
            w.writerow(['Time (s)', 'Voltage (V)', 'Amperage (A)'])
            for i in range(len(self.timestamps)):
                w.writerow([str(self.timestamps[i]), str(self.voltage_values[i]), str(self.amperage_values[i])])

    def TelemetryThread(self):
        while True:
            if self.fake_telemetry:
                self.fake_telemetry_counter += 1
                wx.CallAfter(self.TelemetryCallback,
                             "Fake Telemetry Element " + str(self.fake_telemetry_counter) + "\n")
                time.sleep(0.5)
            else:
                line = self.serial.readline()
                wx.CallAfter(self.TelemetryCallback, line)


if __name__ == '__main__':
    app = wx.App()
    TelemetrySoftware()
    app.MainLoop()
