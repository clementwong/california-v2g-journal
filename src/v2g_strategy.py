import pandas as pd
import numpy as np


from datetime import datetime,  timedelta



# System Constants
L2_KW = 9.6
BATTERY_CAPACITY_KWH = 71.4
V2G_DISCHARGE_KW = 9.6
MIN_SOC = 0.5

     


def is_overnight_charging(start_timestamp: datetime, end_timestamp: datetime) -> bool:
    """
    Checks if a charging session spans across the V2G operational window (9 PM to 4 AM next day).
    
    Args:
        start_timestamp (datetime): The start time of the plug-in session.
        end_timestamp (datetime): The end time of the plug-in session.
        
    Returns:
        bool: True if the session encompasses the 9 PM to 4 AM window, False otherwise.
    """
    # Create a timestamp for 9 PM on the same day as the start_timestamp
    nine_pm_timestamp = start_timestamp.replace(hour=21, minute=0, second=0, microsecond=0)

    # If the start time is already exactly at or past 9 PM, the target 9 PM is the following day.
    if nine_pm_timestamp <= start_timestamp:
        nine_pm_timestamp += timedelta(days=1)

    # The 4 AM timestamp is exactly 7 hours after the 9 PM timestamp
    four_am_timestamp = nine_pm_timestamp + timedelta(hours=7)

    # Return true if the plug-in session extends past the 4 AM completion target
    return four_am_timestamp < end_timestamp







def add_V2G_charge_cycle_df(last_time: float, last_SOC: float, last_timestamp: pd.Timestamp, 
                            SOC_to_charge_to: float, input_min_SOC) -> pd.DataFrame:
    
    # Anchors for same calendar day as last_timestamp
    six_pm = pd.Timestamp(last_timestamp.date()) + pd.Timedelta(hours=18)
    nine_pm = pd.Timestamp(last_timestamp.date()) + pd.Timedelta(hours=21)

    # --- V2G discharge ---
    if 18 <= last_timestamp.hour < 21:
        start_discharge_timestamp = last_timestamp
        start_discharge_time = last_time
    else:
        start_discharge_timestamp = six_pm
        discharge_time_s_to_six = (start_discharge_timestamp - last_timestamp) / timedelta(seconds=1)
        start_discharge_time = last_time + discharge_time_s_to_six

    discharge_time_s_to_nine = (nine_pm - start_discharge_timestamp) / timedelta(seconds=1)


    # Energy discharged until 9pm
    discharge_kwh = (discharge_time_s_to_nine / 3600.0) * -V2G_DISCHARGE_KW
    MIN_SOC = (discharge_kwh / BATTERY_CAPACITY_KWH) + last_SOC
    
    if MIN_SOC < input_min_SOC:
        MIN_SOC = input_min_SOC
    

    SOC_diff = MIN_SOC - last_SOC
    delta_discharge_time_s = np.linspace(1, BATTERY_CAPACITY_KWH* abs(SOC_diff) / V2G_DISCHARGE_KW * 3600, 10)
    discharge_cycle_time = start_discharge_time + delta_discharge_time_s

    discharge_cycle_timestamp = start_discharge_timestamp + pd.to_timedelta(delta_discharge_time_s, unit="s")
    discharge_cycle_SOC = np.linspace(last_SOC, MIN_SOC, 10)

    V2G_discharge_C_rate = V2G_DISCHARGE_KW / BATTERY_CAPACITY_KWH
    discharge_cycle_C_rate = -np.ones_like(discharge_cycle_time) * V2G_discharge_C_rate


    discharge_cycle_df = pd.DataFrame({
        "Time (s)": discharge_cycle_time,
        "SOC": discharge_cycle_SOC,
        "timestamp": pd.Series(discharge_cycle_timestamp),
        "C-rate": discharge_cycle_C_rate,
        "V2G discharge": True,
    })


    # Create bounding rest points for step-function clarity
    first_row = discharge_cycle_df.iloc[0].copy()
    first_row['Time (s)'] -= 1
    first_row['timestamp'] -= pd.Timedelta(seconds=1)
    first_row['C-rate'] = 0.0
    
    last_row = discharge_cycle_df.iloc[-1].copy()
    last_row['Time (s)'] += 1
    last_row['timestamp'] += pd.Timedelta(seconds=1)
    last_row['C-rate'] = 0.0
    
    discharge_cycle_df = pd.concat([pd.DataFrame([first_row]), discharge_cycle_df, pd.DataFrame([last_row])], ignore_index=True)

     
    discharge_cycle_df['Time_diff (s)'] = discharge_cycle_df['Time (s)'].diff().fillna(0)




    
    
    # --- Charging ---
    next_day_user_time_off = (last_timestamp + pd.Timedelta(days=1)).replace(
        hour=4,
        minute=0,
        second=0,
        microsecond=0,
    )

    # Energy needed to reach SOC_to_charge_to
    SOC_diff_charge = SOC_to_charge_to - MIN_SOC
    total_seconds_to_charge = BATTERY_CAPACITY_KWH* abs(SOC_diff_charge) / L2_KW * 3600

    # Start charging so it finishes at user’s time next day
    start_charge_time = (next_day_user_time_off - last_timestamp).total_seconds() + last_time - total_seconds_to_charge
    start_charge_timestamp = next_day_user_time_off - pd.to_timedelta(total_seconds_to_charge, unit="s")

    charge_cycle_df = add_charge_cycle_df(
        start_charge_time, MIN_SOC, start_charge_timestamp, L2_KW, SOC_to_charge_to
    )
    charge_cycle_df["V2G discharge"] = False




    # Add preceding rest point
    charge_first_row = charge_cycle_df.iloc[0].copy()
    charge_first_row['Time (s)'] -= 1
    charge_first_row['timestamp'] -= pd.Timedelta(seconds=1)
    charge_first_row['C-rate'] = 0.0
    
    charge_cycle_df = pd.concat([pd.DataFrame([charge_first_row]), charge_cycle_df], ignore_index=True)

    # Combine discharge + charge
    V2G_charge_cycle_df = pd.concat([discharge_cycle_df, charge_cycle_df], ignore_index=True)
    V2G_charge_cycle_df = V2G_charge_cycle_df.sort_index()

    return V2G_charge_cycle_df


def add_charge_cycle_df(last_time, last_SOC , last_timestamp, charge_kw , SOC_to_charge_to):

    SOC_diff  = SOC_to_charge_to -last_SOC
    delta_charge_time_s= np.linspace(1, BATTERY_CAPACITY_KWH*SOC_diff/charge_kw*3600, 10)
    charge_cycle_time = last_time + delta_charge_time_s

    charge_cycle_timestamp = last_timestamp + pd.to_timedelta(delta_charge_time_s, unit='s')
    timestamp_series = pd.Series(charge_cycle_timestamp)
    charge_cycle_SOC = np.linspace(last_SOC, SOC_to_charge_to, 10)

    charge_C_rate = charge_kw/BATTERY_CAPACITY_KWH


    charge_cycle_C_rate= np.ones_like(charge_cycle_time)*charge_C_rate
    

    # Add rest period 
    


    charge_cycle_df = pd.DataFrame()
    charge_cycle_df['Time (s)'] = charge_cycle_time
    charge_cycle_df['SOC'] = charge_cycle_SOC
    charge_cycle_df['timestamp'] =  timestamp_series
    charge_cycle_df['C-rate'] =charge_cycle_C_rate
    charge_cycle_df['V2G discharge'] = False

    # Add a rest period bound (drop C-rate to 0 at the end)
    last_row = charge_cycle_df.iloc[-1].copy()
    last_row['Time (s)'] += 1
    last_row['timestamp'] += pd.Timedelta(seconds=1)
    last_row['C-rate'] = 0.0
    
    charge_cycle_df = pd.concat([charge_cycle_df, pd.DataFrame([last_row])], ignore_index=True)

    return charge_cycle_df







def integrate_v2g(vehicle_usage_df: pd.DataFrame) -> pd.DataFrame:
    """
    Processes a vehicle's raw time-series usage, identifies overnight plug-in 
    events, and superimposes the V2G operational strategy.
    
    Args:
        vehicle_usage_df (pd.DataFrame): The time-series usage of the BEV.
        
    Returns:
        pd.DataFrame: The modified time-series usage of BEV with V2G integrated.
    """
    
    
    
    # 1. Identify in vehicle usage when the vehicle is plugged in

    total_drive_cycle_df = vehicle_usage_df.copy()
    soc_diff = total_drive_cycle_df['SOC'].diff()
    state = pd.Series(index=total_drive_cycle_df.index, dtype=object)
    
    state[soc_diff < 0] = False
    state[soc_diff > 0] = True
    state[soc_diff.shift(-1) > 0] = True # Catch the valley
    state = state.ffill()
    total_drive_cycle_df['plugged_in'] = np.where(state == True, True, np.nan)
    is_plugged = total_drive_cycle_df['plugged_in'] == True
    new_session_start = is_plugged & ~(is_plugged.shift(1).fillna(False))
    
    total_drive_cycle_df['plugCount'] = np.where(is_plugged, new_session_start.cumsum(), np.nan)



    plugged_in_dfs = total_drive_cycle_df[total_drive_cycle_df['plugCount'].notna()]

    total_drive_cycle_df_with_V2G = total_drive_cycle_df.set_index(['timestamp']).copy()

    # 2. Iteratively process each valid plug-in session

    for i in plugged_in_dfs['plugCount'].unique():
        plugged_in_df = plugged_in_dfs[plugged_in_dfs['plugCount'] == i]

        # Filter out DC Fast Charging events
        fast_charging_kw = 100
        fast_charging_C_rate = fast_charging_kw/BATTERY_CAPACITY_KWH
        if (plugged_in_df['C-rate'].max()< fast_charging_C_rate):


            start_timestamp = plugged_in_df['timestamp'].iloc[0]
            start_SOC = plugged_in_df['SOC'].iloc[0]
            start_time = plugged_in_df['Time (s)'].iloc[0]


            finish_SOC = plugged_in_df['SOC'].iloc[-1]
            finish_charge_time = plugged_in_df['Time (s)'].iloc[-1]
            finish_charge_timestamp = plugged_in_df['timestamp'].iloc[-1]

            temp_timestamp = start_timestamp
            temp_time = start_time
            temp_timestamp = start_timestamp
            temp_SOC = start_SOC

            charge_cycle_df = pd.DataFrame()
            # If it qualifies as an overnight session, integrate V2G
            while ((temp_timestamp< finish_charge_timestamp) & (is_overnight_charging(temp_timestamp, finish_charge_timestamp))): 
                if ((temp_SOC>MIN_SOC )):
                    temp_charge_cycle_df   = add_V2G_charge_cycle_df(temp_time , temp_SOC , temp_timestamp, finish_SOC, MIN_SOC)
                else: 
                        
                    if (finish_SOC>temp_SOC):
                        # Add Charge cycle
                        charge_kw = L2_KW
                        temp_charge_cycle_df  = add_charge_cycle_df(temp_time , temp_SOC , temp_timestamp, charge_kw ,finish_SOC)

                
                charge_cycle_df  = pd.concat([charge_cycle_df, temp_charge_cycle_df], axis=0)
                
                temp_time = temp_charge_cycle_df['Time (s)'].iloc[-1]
                temp_timestamp = temp_charge_cycle_df['timestamp'].iloc[-1]
                temp_SOC = finish_SOC
            # If V2G cycles were added, swap out the raw data points
            if ( charge_cycle_df.empty == False):
                charge_cycle_df.set_index('timestamp', inplace= True)
                plugged_in_df.set_index('timestamp', inplace= True)
                total_drive_cycle_df_with_V2G = total_drive_cycle_df_with_V2G.drop(plugged_in_df.index[0:-1])
                total_drive_cycle_df_with_V2G = pd.concat([total_drive_cycle_df_with_V2G, charge_cycle_df])
    total_drive_cycle_df_with_V2G.sort_index(inplace=True)
    total_drive_cycle_df_with_V2G.reset_index(inplace=True)
    return total_drive_cycle_df_with_V2G


     