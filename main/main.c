#include <stdio.h>
#include <stdint.h>
#include <stdbool.h>
#include <stdlib.h>
#include <math.h>

#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

#include "driver/i2c_master.h"
#include "esp_err.h"
#include "esp_timer.h"


/* ============================================================
   HARDWARE
   ============================================================ */

#define I2C_SDA_GPIO       21
#define I2C_SCL_GPIO       22

#define SENSOR_ADDR        0x68

#define REG_PWR_MGMT_1     0x6B
#define REG_ACCEL_CONFIG   0x1C
#define REG_GYRO_CONFIG    0x1B
#define REG_ACCEL_XOUT_H   0x3B

#define ACCEL_SCALE        4096.0f
#define GYRO_SCALE         32.8f


/* ============================================================
   AIM CALIBRATION
   ============================================================ */

#define AIM_LEFT_AY       -0.97f
#define AIM_CENTER_AY     -0.07f
#define AIM_RIGHT_AY       0.81f

#define AIM_DEADZONE       6


/* ============================================================
   KICK DETECTION
   ============================================================ */

#define START_THRESHOLD_G      0.55f
#define START_GYRO_DPS         80.0f

#define CAPTURE_TIME_MS        200
#define COOLDOWN_MS            700


/* ============================================================
   RE-ARM SYSTEM

   Normal re-arm:
       motion < 0.40g for 150 ms

   Safety fallback:
       if that never happens, re-arm after 1.2 seconds
   ============================================================ */

#define REARM_MOTION_G         0.40f
#define REARM_TIME_MS          150
#define FORCE_REARM_MS         1200


/* ============================================================
   POWER
   ============================================================ */

#define MIN_POWER_G            0.70f
#define MAX_POWER_G            3.50f


/* ============================================================
   I2C HANDLES
   ============================================================ */

static i2c_master_bus_handle_t bus_handle;
static i2c_master_dev_handle_t sensor_handle;


/* ============================================================
   WRITE REGISTER
   ============================================================ */

static esp_err_t write_reg(
    uint8_t reg,
    uint8_t value
)
{
    uint8_t data[2] = {
        reg,
        value
    };

    return i2c_master_transmit(
        sensor_handle,
        data,
        sizeof(data),
        100
    );
}


/* ============================================================
   READ SENSOR
   ============================================================ */

static esp_err_t read_sensor(
    float *ax,
    float *ay,
    float *az,
    float *gx,
    float *gy,
    float *gz
)
{
    uint8_t reg = REG_ACCEL_XOUT_H;
    uint8_t data[14];

    esp_err_t err =
        i2c_master_transmit_receive(
            sensor_handle,
            &reg,
            1,
            data,
            sizeof(data),
            100
        );

    if (err != ESP_OK)
    {
        return err;
    }


    int16_t raw_ax =
        (int16_t)(
            ((uint16_t)data[0] << 8)
            | data[1]
        );

    int16_t raw_ay =
        (int16_t)(
            ((uint16_t)data[2] << 8)
            | data[3]
        );

    int16_t raw_az =
        (int16_t)(
            ((uint16_t)data[4] << 8)
            | data[5]
        );


    int16_t raw_gx =
        (int16_t)(
            ((uint16_t)data[8] << 8)
            | data[9]
        );

    int16_t raw_gy =
        (int16_t)(
            ((uint16_t)data[10] << 8)
            | data[11]
        );

    int16_t raw_gz =
        (int16_t)(
            ((uint16_t)data[12] << 8)
            | data[13]
        );


    *ax = raw_ax / ACCEL_SCALE;
    *ay = raw_ay / ACCEL_SCALE;
    *az = raw_az / ACCEL_SCALE;

    *gx = raw_gx / GYRO_SCALE;
    *gy = raw_gy / GYRO_SCALE;
    *gz = raw_gz / GYRO_SCALE;


    return ESP_OK;
}


/* ============================================================
   AIM
   ============================================================ */

static int calculate_aim(float ay)
{
    float normalized;


    if (ay < AIM_CENTER_AY)
    {
        normalized =
            (ay - AIM_CENTER_AY)
            /
            (AIM_CENTER_AY - AIM_LEFT_AY);
    }
    else
    {
        normalized =
            (ay - AIM_CENTER_AY)
            /
            (AIM_RIGHT_AY - AIM_CENTER_AY);
    }


    if (normalized < -1.0f)
    {
        normalized = -1.0f;
    }


    if (normalized > 1.0f)
    {
        normalized = 1.0f;
    }


    int aim =
        (int)roundf(
            normalized * 100.0f
        );


    if (abs(aim) <= AIM_DEADZONE)
    {
        aim = 0;
    }


    return aim;
}


/* ============================================================
   POWER
   ============================================================ */

static int calculate_power(float peak_motion)
{
    if (peak_motion <= MIN_POWER_G)
    {
        return 1;
    }


    if (peak_motion >= MAX_POWER_G)
    {
        return 100;
    }


    float normalized =
        (peak_motion - MIN_POWER_G)
        /
        (MAX_POWER_G - MIN_POWER_G);


    int power =
        1
        +
        (int)(
            normalized * 99.0f
        );


    if (power < 1)
    {
        power = 1;
    }


    if (power > 100)
    {
        power = 100;
    }


    return power;
}


/* ============================================================
   MAIN
   ============================================================ */

void app_main(void)
{
    printf("\n\n");
    printf("========================================\n");
    printf("       ESP32 MOTION FOOTBALL\n");
    printf("========================================\n\n");


    /* ========================================================
       I2C BUS
       ======================================================== */

    i2c_master_bus_config_t bus_config = {

        .i2c_port =
            I2C_NUM_0,

        .sda_io_num =
            I2C_SDA_GPIO,

        .scl_io_num =
            I2C_SCL_GPIO,

        .clk_source =
            I2C_CLK_SRC_DEFAULT,

        .glitch_ignore_cnt =
            7,

        .flags.enable_internal_pullup =
            true
    };


    ESP_ERROR_CHECK(
        i2c_new_master_bus(
            &bus_config,
            &bus_handle
        )
    );


    /* ========================================================
       SENSOR DEVICE
       ======================================================== */

    i2c_device_config_t dev_config = {

        .dev_addr_length =
            I2C_ADDR_BIT_LEN_7,

        .device_address =
            SENSOR_ADDR,

        .scl_speed_hz =
            100000
    };


    ESP_ERROR_CHECK(
        i2c_master_bus_add_device(
            bus_handle,
            &dev_config,
            &sensor_handle
        )
    );


    /* Wake sensor */

    ESP_ERROR_CHECK(
        write_reg(
            REG_PWR_MGMT_1,
            0x00
        )
    );


    vTaskDelay(
        pdMS_TO_TICKS(100)
    );


    /* Accelerometer ±8g */

    ESP_ERROR_CHECK(
        write_reg(
            REG_ACCEL_CONFIG,
            0x10
        )
    );


    /* Gyroscope ±1000 dps */

    ESP_ERROR_CHECK(
        write_reg(
            REG_GYRO_CONFIG,
            0x10
        )
    );


    printf("Sensor ready.\n");
    printf("Slow hand tilt = AIM\n");
    printf("Fast hand swing = KICK\n\n");


    /* ========================================================
       FILTERS
       ======================================================== */

    float filtered_ay =
        AIM_CENTER_AY;


    float filtered_motion =
        0.0f;


    /* ========================================================
       KICK STATE
       ======================================================== */

    bool capturing =
        false;


    /*
     * Start armed.
     *
     * This means you don't have to wait for a special
     * settling period immediately after startup.
     */

    bool armed =
        true;


    int64_t capture_start_ms =
        0;


    int64_t last_kick_ms =
        -COOLDOWN_MS;


    /*
     * Time at which the previous kick finished.
     *
     * Used by the forced re-arm fallback.
     */

    int64_t disarmed_since_ms =
        0;


    /*
     * Start of quiet period.
     */

    int64_t quiet_start_ms =
        0;


    float peak_motion =
        0.0f;


    float peak_gyro =
        0.0f;


    /*
     * Freeze direction at the START of a kick.
     */

    int frozen_kick_aim =
        0;


    int last_aim_sent =
        999;


    /* ========================================================
       SENSOR LOOP
       ======================================================== */

    while (1)
    {
        float ax;
        float ay;
        float az;

        float gx;
        float gy;
        float gz;


        esp_err_t err =
            read_sensor(
                &ax,
                &ay,
                &az,
                &gx,
                &gy,
                &gz
            );


        if (err != ESP_OK)
        {
            printf(
                "SENSOR_ERROR:%s\n",
                esp_err_to_name(err)
            );


            vTaskDelay(
                pdMS_TO_TICKS(100)
            );


            continue;
        }


        /* ====================================================
           MOTION
           ==================================================== */

        float accel_magnitude =
            sqrtf(
                ax * ax
                +
                ay * ay
                +
                az * az
            );


        float dynamic_motion =
            fabsf(
                accel_magnitude
                - 1.0f
            );


        filtered_motion =
            0.35f * filtered_motion
            +
            0.65f * dynamic_motion;


        /* ====================================================
           GYROSCOPE
           ==================================================== */

        float gyro_magnitude =
            sqrtf(
                gx * gx
                +
                gy * gy
                +
                gz * gz
            );


        int64_t now_ms =
            esp_timer_get_time()
            /
            1000;


        /* ====================================================
           AIMING
           ==================================================== */

        if (!capturing)
        {
            filtered_ay =
                0.80f * filtered_ay
                +
                0.20f * ay;


            int aim =
                calculate_aim(
                    filtered_ay
                );


            if (
                last_aim_sent == 999
                ||
                abs(
                    aim -
                    last_aim_sent
                ) >= 2
            )
            {
                printf(
                    "AIM:%d\n",
                    aim
                );


                last_aim_sent =
                    aim;
            }
        }


        /* ====================================================
           RE-ARM

           After every kick we disarm.

           Normally:
             motion must settle below 0.40g for 150 ms.

           Fallback:
             if that doesn't happen because of noise,
             automatically re-arm after 1.2 seconds.
           ==================================================== */

        if (
            !capturing
            &&
            !armed
        )
        {
            /*
             * NORMAL RE-ARM
             */

            if (
                filtered_motion
                <= REARM_MOTION_G
            )
            {
                if (
                    quiet_start_ms == 0
                )
                {
                    quiet_start_ms =
                        now_ms;
                }


                if (
                    now_ms
                    -
                    quiet_start_ms
                    >= REARM_TIME_MS
                )
                {
                    armed =
                        true;


                    quiet_start_ms =
                        0;


                    printf(
                        "READY\n"
                    );
                }
            }
            else
            {
                /*
                 * Motion became strong again.
                 * Restart quiet timer.
                 */

                quiet_start_ms =
                    0;
            }


            /*
             * FORCED RE-ARM FALLBACK
             *
             * This prevents the detector from becoming
             * permanently stuck after several kicks.
             */

            if (
                !armed
                &&
                disarmed_since_ms > 0
                &&
                now_ms
                -
                disarmed_since_ms
                >= FORCE_REARM_MS
            )
            {
                armed =
                    true;


                quiet_start_ms =
                    0;


                printf(
                    "READY\n"
                );
            }
        }


        /* ====================================================
           START KICK
           ==================================================== */

        if (
            !capturing
            &&
            armed
        )
        {
            bool cooldown_finished =
                (
                    now_ms
                    -
                    last_kick_ms
                )
                >= COOLDOWN_MS;


            /*
             * BOTH acceleration and rotation are required.
             */

            if (
                cooldown_finished
                &&
                filtered_motion
                    >= START_THRESHOLD_G
                &&
                gyro_magnitude
                    >= START_GYRO_DPS
            )
            {
                capturing =
                    true;


                /*
                 * Immediately disarm.
                 *
                 * This prevents the same physical swing
                 * from creating multiple shots.
                 */

                armed =
                    false;


                capture_start_ms =
                    now_ms;


                peak_motion =
                    filtered_motion;


                peak_gyro =
                    gyro_magnitude;


                /*
                 * Freeze the current aim BEFORE the
                 * aggressive kick movement changes AY.
                 */

                frozen_kick_aim =
                    calculate_aim(
                        filtered_ay
                    );


                /*
                 * Send frozen aim immediately.
                 */

                printf(
                    "AIM:%d\n",
                    frozen_kick_aim
                );
            }
        }


        /* ====================================================
           CAPTURE KICK
           ==================================================== */

        if (capturing)
        {
            if (
                filtered_motion
                >
                peak_motion
            )
            {
                peak_motion =
                    filtered_motion;
            }


            if (
                gyro_magnitude
                >
                peak_gyro
            )
            {
                peak_gyro =
                    gyro_magnitude;
            }


            /*
             * Wait 200 ms so we capture the strongest
             * part of the complete swing.
             */

            if (
                now_ms
                -
                capture_start_ms
                >= CAPTURE_TIME_MS
            )
            {
                int power =
                    calculate_power(
                        peak_motion
                    );


                /* ============================================
                   SEND SHOT TO PYTHON
                   ============================================ */

                printf(
                    "KICK:%d\n",
                    power
                );


                printf(
                    "SHOT_DATA:motion=%.2f gyro=%.0f aim=%d power=%d\n",
                    peak_motion,
                    peak_gyro,
                    frozen_kick_aim,
                    power
                );


                /* ============================================
                   FINISH SHOT
                   ============================================ */

                capturing =
                    false;


                last_kick_ms =
                    now_ms;


                /*
                 * Start re-arm period.
                 */

                disarmed_since_ms =
                    now_ms;


                quiet_start_ms =
                    0;
            }
        }


        /*
         * Approximately 50 sensor samples per second.
         */

        vTaskDelay(
            pdMS_TO_TICKS(20)
        );
    }
}