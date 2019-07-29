﻿from DataGenerate.GetDataset import train_or_eval_input_fn
import tensorflow as tf
import os
import argparse
import psp_tools
import datetime
import math

os.environ['CUDA_VISIBLE_DEVICES'] = '0'

batch_size = 4
summary_path = "./psp_summary/"
checkpoint_path = "./psp_checkpoint/"
EPOCHS = 100
train_set_length = 5000
eval_set_length = 500

parser = argparse.ArgumentParser()

#添加参数
envarg = parser.add_argument_group('Training params')
# BN params
envarg.add_argument("--batch_norm_epsilon", type=float, default=1e-5, help="batch norm epsilon argument for batch normalization")
envarg.add_argument('--batch_norm_decay', type=float, default=0.9997, help='batch norm decay argument for batch normalization.')
envarg.add_argument('--freeze_batch_norm', type=bool, default=True,  help='Freeze batch normalization parameters during the training.')
# the number of classes
envarg.add_argument("--number_of_classes", type=int, default=16, help="Number of classes to be predicted.")

# regularizer
envarg.add_argument("--l2_regularizer", type=float, default=0.0001, help="l2 regularizer parameter.")

# the base network
envarg.add_argument("--resnet_model", default="resnet_v2_101", choices=["resnet_v2_50", "resnet_v2_101", "resnet_v2_152", "resnet_v2_200"], help="Resnet model to use as feature extractor. Choose one of: resnet_v2_50 or resnet_v2_101")

# the pre_trained model for example resnet50 101 and so on
envarg.add_argument('--pre_trained_model', type=str, default='./pre_trained_model/resnet_v2_101/resnet_v2_101.ckpt',
                    help='Path to the pre-trained model checkpoint.')

# max number of batch elements to tensorboard
parser.add_argument('--tensorboard_images_max_outputs', type=int, default=4,
                    help='Max number of batch elements to generate for Tensorboard.')
# poly learn_rate
parser.add_argument('--initial_learning_rate', type=float, default=5e-3,
                    help='Initial learning rate for the optimizer.')

parser.add_argument('--end_learning_rate', type=float, default=1e-6,
                    help='End learning rate for the optimizer.')

parser.add_argument('--initial_global_step', type=int, default=0,
                    help='Initial global step for controlling learning rate when fine-tuning model.')
parser.add_argument('--max_iter', type=int, default=125000,
                    help='Number of maximum iteration used for "poly" learning rate policy.')
args = parser.parse_args()

def main():
    os.environ['TF_ENABLE_WINOGRAD_NONFUSED'] = '0'

    is_train = tf.placeholder(tf.bool, shape=[])
    x = tf.placeholder(dtype=tf.float32, shape=[None, None, None, 3], name="image_batch")
    y = tf.placeholder(dtype=tf.int32, shape=[None, None, None, 1], name="label_batch")

    train_dataset = train_or_eval_input_fn(is_training=True,
                                           data_dir="/2T/tzj/semantic_segmentation_contest/DatasetNew/train/", batch_size=batch_size)
    eval_dataset = train_or_eval_input_fn(is_training=False,
                                           data_dir="/2T/tzj/semantic_segmentation_contest/DatasetNew/val/", batch_size=batch_size, num_epochs=1)
    iterator_train = tf.data.Iterator.from_structure(train_dataset.output_types, train_dataset.output_shapes)
    next_batch = iterator_train.get_next()
    training_init_op = iterator_train.make_initializer(train_dataset)
    evaling_init_op = iterator_train.make_initializer(eval_dataset)

    loss, train_op, metrics = psp_tools.get_loss_pre_metrics(x, y, is_train, batch_size, args)

    accuracy = metrics["px_accuracy"]
    mean_iou = metrics["mean_iou"]
    confusion_matrix = metrics['confusion_matrix']

    summary_op = tf.summary.merge_all()
    init_op = tf.group(
        tf.local_variables_initializer(),
        tf.global_variables_initializer()
    )

    saver = tf.train.Saver(max_to_keep=100)
    summary_writer_train = tf.summary.FileWriter(summary_path + "train/")
    summary_writer_val = tf.summary.FileWriter(summary_path + "val/")
    # 运行图
    config = tf.ConfigProto()
    config.gpu_options.allow_growth = True
    with tf.Session(config=config) as sess:
        sess.run(init_op, feed_dict={is_train: True})
        ckpt = tf.train.get_checkpoint_state(checkpoint_path)
        if ckpt and ckpt.model_checkpoint_path:
            saver.restore(sess, ckpt.model_checkpoint_path)
            print("restored")
        sess.graph.finalize()

        train_batches_of_epoch = int(math.ceil(train_set_length / batch_size))
        val_batches_of_epoch = int(math.ceil(eval_set_length / batch_size))
        for epoch in range(EPOCHS):
            sess.run(training_init_op)
            print("{} Epoch number: {}".format(datetime.datetime.now(), epoch + 1))
            # step = 1
            for step in range((epoch * train_batches_of_epoch), ((epoch + 1) * train_batches_of_epoch)):
                img_batch, label_batch = sess.run(next_batch)
                sess.run([train_op], feed_dict={x: img_batch, y: label_batch, is_train: True})

                if (step + 1) % 625 == 0:
                    loss_value, acc, m_iou, con_matrix = sess.run(
                        [loss, accuracy, mean_iou, confusion_matrix],
                        feed_dict={x: img_batch, y: label_batch, is_train: True})
                    kappa = psp_tools.kappa(con_matrix)
                    print("{} {} loss = {:.4f}".format(datetime.datetime.now(), step + 1, loss_value))
                    print("accuracy{}".format(acc))
                    print("miou{}".format(m_iou))
                    print("kappa{}".format(kappa))
                    merge = sess.run(summary_op, feed_dict={x: img_batch, y: label_batch, is_train: True})
                    summary_writer_train.add_summary(merge, step + 1)
            saver.save(sess, checkpoint_path + "model.ckpt", epoch + 1)
            print("checkpoint saved")

            # 验证过程
            sess.run(evaling_init_op)
            print("{} Start validation".format(datetime.datetime.now()))
            test_acc = 0.0
            test_miou = 0.0
            test_kappa = 0.0
            test_count = 0
            for tag in range(val_batches_of_epoch):
                img_batch, label_batch = sess.run(next_batch)
                acc, m_iou, con_matrix = sess.run(
                    [accuracy, mean_iou, confusion_matrix],
                    feed_dict={x: img_batch, y: label_batch, is_train: False})

                kappa = psp_tools.kappa(con_matrix)
                test_kappa += kappa
                test_acc += acc
                test_miou += m_iou
                test_count += 1
            test_acc /= test_count
            test_miou /= test_count
            test_kappa /= test_count
            s = tf.Summary(value=[
                tf.Summary.Value(tag="validation_accuracy", simple_value=test_acc),
                tf.Summary.Value(tag="validation_miou", simple_value=test_miou),
                tf.Summary.Value(tag="validation_kappa", simple_value=test_kappa)
            ])
            summary_writer_val.add_summary(s, epoch + 1)
            print("{} Validation Accuracy = {:.4f}".format(datetime.datetime.now(), test_acc))
            print("{} Validation miou = {:.4f}".format(datetime.datetime.now(), test_miou))
            print("{} Validation kappa = {:.4f}".format(datetime.datetime.now(), test_kappa))

if __name__ == '__main__':
  tf.logging.set_verbosity(tf.logging.INFO)
  main()