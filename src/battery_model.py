import numpy as np
from numba import njit

# Parameters for the NREL battery model

parameters = {
    "LFP|Gr": {
        "p1": 8.213e+04, 
        "p2": -5.200e+03, 
        "p3": -3.571e+03, 
        "p4": 5.257e-01,
        "p5": 4.314e-08, 
        "p6": 1.698e-08, 
        "p7": 1.637e-07, 
        "p8": 2.193e+03, 
        "p9": 1.606e+05, 
        "p10": 8.306e-01
    }, 
    "NMC|Gr B1": {
        "p1": 1.333e+02, 
        "p2": -3.300e+03, 
        "p3": -3.664e+03, 
        "p4": 6.818e-01,
        "p5": 1.220e-08, 
        "p6": 1.295e-03, 
        "p7": 2.342e-04, 
        "p8": 2.041e-10, 
        "p9": 4.987e+02, 
        "p10": 5.574e-01
    },
    "NMC|Gr B2": {
        "p1": 1.668e+02, 
        "p2": -2.812e+03, 
        "p3": -4.768e+03, 
        "p4": 3.543e-01,
        "p5": 2.995e-18, 
        "p6": 9.340e-06, 
        "p7": 3.637e-06, 
        "p8": 4.625e+02, 
        "p9": 2.922e+05, 
        "p10": 1.057e+00
    }
}



def Ua_function(xa: float) -> float:
    """
    Calculates the negative electrode voltage, Ua, as a function of xa.
    
    Args:
        xa (float): Lithium stoichiometry of the negative electrode.
        
    Returns:
        float: Negative electrode voltage.
    """
    term1 = 0.6379
    term2 = 0.5416 * np.exp(-305.5309 * xa)
    term3 = 0.044 * np.tanh(-(xa - 0.1958) / 0.1088)
    term4 = -0.1978 * np.tanh((xa - 1.0571) / 0.0854)
    term5 = -0.6875 * np.tanh((xa + 0.0117) / 0.0529)
    term6 = -0.0175 * np.tanh((xa - 0.5692) / 0.0875)
    
    return term1 + term2 + term3 + term4 + term5 + term6


def xa(SOC: float) -> float:
    """
    Calculates xa, the lithium stoichiometry of the negative electrode.
    
    Args:
        SOC (float): State of charge (fractional, 0 to 1).
        
    Returns:
        float: Lithium stoichiometry.
    """
    return 0.0085 + SOC * (0.78 - 0.0085)

def calculate_weighted_avg_soc(time_array: np.ndarray, SOC_array: np.ndarray) -> float:
    """
    Calculates the weighted average SOC from a time-series array.
    
    Args:
        time_array (np.ndarray): Array of time data in seconds.
        SOC_array (np.ndarray): Array of SOC data corresponding to time_array.

    Returns:
        float: The time-weighted average SOC.
    """

    
    time_diff = np.diff(time_array, prepend=time_array[0])  
    weighted_SOC = SOC_array *time_diff
    return weighted_SOC.sum()/time_diff.sum()



@njit
def q_loss_cal_function(T, Ua, time_seconds, p1, p2, p3, p4):
    """
    Analytically computes the calendar capacity loss array.
    """
    # (1 / (3600 * 24)) converts seconds to days for the empirical parameter p4
    return p1 * np.exp(p2 / T) * np.exp(p3 * Ua / T) * (time_seconds**p4)*(1/(3600*24))**p4



@njit
def dq_loss_cyc(T, SOC_k, C_rate_k, EFC_k, p5, p6, p7, p8, p9, p10): # This stays the same 


  
    temp_constant = (np.exp(p8 / T) + np.exp(-p9 / T))

    
    return temp_constant * (((p5+ p6 * (1 - SOC_k) + p7 * np.abs(C_rate_k))
                                * (p10 * EFC_k**(p10 - 1)* (np.abs(C_rate_k/2) / 3600)) 
                                ))



@njit

def capacity_degradation_njit (SOC_array, C_rate_array, EFC_time_seconds_array,  T, Ua, p1, p2, p3, p4, p5, p6, p7, p8, p9, p10):
    """
    Numba-accelerated forward Euler integration for battery degradation.
    """

    abs_C_rate_array = np.abs((C_rate_array))
 
    ## Initializing array to store simulated values

   
    q_loss_cal =q_loss_cal_function(T, Ua, EFC_time_seconds_array, p1, p2, p3, p4)

    # Initialize arrays
    q_loss_cyc  =np.zeros(np.shape(EFC_time_seconds_array))
    EFC = np.zeros(np.shape(C_rate_array))
    
    # Initial Conditions 
    EFC[0] =1
    # Apply Forward Euler Integration
    for k in range(0,len(C_rate_array)-1):
    
        delta_time = EFC_time_seconds_array[k+1]-EFC_time_seconds_array[k]
        # # Update the integral EFC using the trapezoidal rule approximation
        EFC[k+1] = EFC[k] + ((abs_C_rate_array[k] /2) + (abs_C_rate_array[k+1] /2))/2  * delta_time/ 3600
    
    
        q_loss_cyc[k+1] = q_loss_cyc[k] + dq_loss_cyc(T, SOC_array[k],abs_C_rate_array[k], EFC[k], p5, p6, p7, p8, p9, p10)* delta_time
        

    q_loss_euler_seconds= 1- q_loss_cyc- q_loss_cal

    return q_loss_euler_seconds, 1- q_loss_cyc, 1-  q_loss_cal, EFC

def calculate_capacity_loss (SOC_array, C_rate_array, time_seconds_array,  chemistry_of_interest, temp_avg):

    """
    Simulates capacity loss given usage data and chemistry of interest
    
    Parameters:
    SOC_array: Time-series of State of Charge.
    C_rate_array: Time-series of C-rate values.
    time_seconds_array : Time-series of time (seconds) values.
    chemistry_of_interest (string): 'LFP|Gr', 'NMC|Gr B1', or 'NMC|Gr B2'.
    temp_avg (float): Time-averaged battery pack temperature (K).
    dt (float): Sampling period in hours.
    total_time_steps (int): Total number of increments in the simulation.
    """

    ### difference between capacity_degradation is that calendar aging does not apply forward euler


    ## Get Parameters

    params = parameters[chemistry_of_interest]
    p1, p2, p3, p4, p5, p6, p7, p8, p9, p10 = (
            params["p1"], params["p2"], params["p3"], params["p4"],
            params["p5"], params["p6"], params["p7"], params["p8"],
            params["p9"], params["p10"]
        )

    ## Get weighted average SOC 
    weighted_avg_soc= calculate_weighted_avg_soc(time_seconds_array, SOC_array)
    Ua_avg = Ua_function(xa(weighted_avg_soc))

    q_loss_euler_seconds, cyc_aging , cal_aging, _ = capacity_degradation_njit (SOC_array, C_rate_array, time_seconds_array,  temp_avg, Ua_avg, p1, p2, p3, p4, p5, p6, p7, p8, p9, p10)

    return q_loss_euler_seconds, cyc_aging , cal_aging
    



